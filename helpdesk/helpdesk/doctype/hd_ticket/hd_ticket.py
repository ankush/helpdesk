from __future__ import unicode_literals

import json
from datetime import timedelta
from email.utils import parseaddr
from functools import lru_cache
from typing import List

import frappe
from frappe import _
from frappe.core.utils import get_parent_doc
from frappe.desk.form.assign_to import add as assign
from frappe.desk.form.assign_to import clear as clear_all_assignments
from frappe.email.inbox import link_communication_to_document
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.query_builder import Case, DocType, Order
from frappe.utils import date_diff, get_datetime, now_datetime, time_diff_in_seconds
from frappe.utils.user import is_website_user
from pypika.functions import Count
from pypika.queries import Query
from pypika.terms import Criterion

from helpdesk.consts import DEFAULT_TICKET_PRIORITY, DEFAULT_TICKET_TYPE
from helpdesk.helpdesk.doctype.hd_ticket_activity.hd_ticket_activity import (
	log_ticket_activity,
)
from helpdesk.helpdesk.utils.email import (
	default_outgoing_email_account,
	default_ticket_outgoing_email_account,
)
from helpdesk.utils import capture_event, get_customer, is_agent, publish_event


class HDTicket(Document):
	@staticmethod
	def get_list_select(query: Query):
		QBTicket = frappe.qb.DocType("HD Ticket")
		QBComment = frappe.qb.DocType("HD Ticket Comment")
		QBCommunication = frappe.qb.DocType("Communication")

		count_comment = (
			frappe.qb.from_(QBComment)
			.select(Count("*"))
			.as_("count_comment")
			.where(QBComment.reference_ticket == QBTicket.name)
		)

		count_communication = (
			frappe.qb.from_(QBCommunication)
			.select(Count("*"))
			.as_("count_communication")
			.where(QBCommunication.reference_doctype == "HD Ticket")
			.where(QBCommunication.reference_name == QBTicket.name)
		)

		query = (
			query.select(QBTicket.star)
			.select(count_comment)
			.select(count_communication)
		)

		return query

	@staticmethod
	def get_list_filters(query: Query):
		QBTeam = frappe.qb.DocType("HD Team")
		QBTeamMember = frappe.qb.DocType("HD Team Member")
		QBTicket = frappe.qb.DocType("HD Ticket")
		user = frappe.session.user
		customer = get_customer(user)
		conditions = (
			[
				QBTicket.contact == user,
				QBTicket.customer == customer,
				QBTicket.raised_by == user,
			]
			if not is_agent()
			else []
		)
		query = query.where(Criterion.any(conditions))

		enable_restrictions, ignore_restrictions = frappe.get_value(
			doctype="HD Settings",
			fieldname=[
				"restrict_tickets_by_agent_group",
				"do_not_restrict_tickets_without_an_agent_group",
			],
		)
		enable_restrictions = bool(int(enable_restrictions))
		ignore_restrictions = bool(int(ignore_restrictions))

		if not enable_restrictions:
			return query

		teams = (
			frappe.qb.from_(QBTeamMember)
			.where(QBTeamMember.user == user)
			.join(QBTeam)
			.on(QBTeam.name == QBTeamMember.parent)
			.select(QBTeam.team_name, QBTeam.ignore_restrictions)
			.run(as_dict=True)
		)

		can_ignore_restrictions = (
			len(list(filter(lambda x: x.ignore_restrictions, teams))) > 0
		)

		if can_ignore_restrictions:
			return query

		conditions = [QBTicket.agent_group == team.team_name for team in teams]

		# Consider tickets without any assigned agent group
		if ignore_restrictions:
			conditions.append(QBTicket.agent_group.isnull())

		query = query.where(Criterion.any(conditions))
		return query

	@staticmethod
	@lru_cache
	def sort_options():
		def by_priority(query: Query, direction: Order):
			QBTicket = frappe.qb.DocType("HD Ticket")
			QBPriority = frappe.qb.DocType("HD Ticket Priority")

			query = (
				query.left_join(QBPriority)
				.on(QBPriority.name == QBTicket.priority)
				.orderby(QBPriority.integer_value, order=direction)
				.orderby(QBTicket.resolution_by, order=Order.desc)
			)

			return query

		return {
			"Due date": ("resolution_by", Order.asc),
			"Created on": ("creation", Order.asc),
			"High to low priority": lambda q: by_priority(q, Order.asc),
			"Low to high priority": lambda q: by_priority(q, Order.desc),
			"Last modified on": "modified",
		}

	def publish_update(self):
		publish_event("helpdesk:ticket-update", {"name": self.name})
		capture_event("ticket_updated")

	def autoname(self):
		return self.name

	def get_feed(self):
		return "{0}: {1}".format(_(self.status), self.subject)

	def before_validate(self):
		self.set_ticket_type()
		self.set_raised_by()
		self.set_contact()
		self.set_customer()
		self.set_priority()

	def validate(self):
		self.validate_ticket_type()

	def after_insert(self):
		log_ticket_activity(self.name, "created this ticket")
		capture_event("ticket_created")

	def on_update(self):
		self.handle_ticket_activity_update()
		self.remove_assignment_if_not_in_team()
		self.publish_update()

	def set_ticket_type(self):
		if self.ticket_type:
			return
		settings = frappe.get_doc("HD Settings")
		ticket_type = settings.default_ticket_type or DEFAULT_TICKET_TYPE
		self.ticket_type = ticket_type

	def set_raised_by(self):
		self.raised_by = self.raised_by or frappe.session.user

	def set_contact(self):
		email_id = parseaddr(self.raised_by)[1]
		if email_id:
			if not self.contact:
				contact = frappe.db.get_value("Contact", {"email_id": email_id})
				if contact:
					self.contact = contact

	def set_customer(self):
		"""
		Update `Customer` if does not exist already. `Contact` is assumed
		to be set beforehand.
		"""
		# Skip if `Customer` is already set
		if self.customer:
			return
		self.customer = get_customer(self.contact)

	def set_priority(self):
		if self.priority:
			return
		self.priority = (
			frappe.get_cached_value("HD Ticket Type", self.ticket_type, "priority")
			or frappe.get_cached_value("HD Settings", "HD Settings", "default_priority")
			or DEFAULT_TICKET_PRIORITY
		)

	def validate_ticket_type(self):
		settings = frappe.get_doc("HD Settings")
		if settings.is_ticket_type_mandatory and not self.ticket_type:
			frappe.throw(_("Ticket type is mandatory"))

	def handle_ticket_activity_update(self):
		"""
		Handles the ticket activity update.
		Should be called inside on_update
		"""
		field_maps = {
			"status": "status",
			"priority": "priority",
			"agent_group": "team",
			"ticket_type": "type",
			"contact": "contact",
		}
		for field in [
			"status",
			"priority",
			"agent_group",
			"contact",
			"ticket_type",
		]:
			if self.has_value_changed(field):
				log_ticket_activity(
					self.name, f"set {field_maps[field]} to {self.as_dict()[field]}"
				)

	def remove_assignment_if_not_in_team(self):
		"""
		Removes the assignment if the agent is not in the team.
		Should be called inside on_update
		"""
		if self.has_value_changed("agent_group") and self.status == "Open":
			current_assigned_agent_doc = self.get_assigned_agent()
			if (
				current_assigned_agent_doc
				and not current_assigned_agent_doc.in_group(self.agent_group)
			) and frappe.get_doc(
				"Assignment Rule",
				frappe.get_doc("HD Team", self.agent_group).assignment_rule,
			).users:
				clear_all_assignments("HD Ticket", self.name)
				frappe.publish_realtime(
					"helpdesk:update-ticket-assignee",
					{"ticket_id": self.name},
					after_commit=True,
				)

	def create_communication(self):
		communication = frappe.new_doc("Communication")
		communication.update(
			{
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"email_status": "Open",
				"subject": self.subject,
				"sender": self.raised_by,
				"content": self.description,
				"status": "Linked",
				"reference_doctype": "HD Ticket",
				"reference_name": self.name,
			}
		)
		communication.ignore_permissions = True
		communication.ignore_mandatory = True
		communication.save(ignore_permissions=True)

	@frappe.whitelist()
	def split_ticket(self, subject, communication_id):
		# Bug: Pressing enter doesn't send subject
		from copy import deepcopy

		replicated_ticket = deepcopy(self)
		replicated_ticket.subject = subject
		replicated_ticket.ticket_split_from = self.name
		replicated_ticket.first_response_time = 0
		replicated_ticket.first_responded_on = None
		replicated_ticket.creation = now_datetime()

		# Reset SLA
		if replicated_ticket.sla:
			replicated_ticket.service_level_agreement_creation = now_datetime()
			replicated_ticket.sla = None
			replicated_ticket.agreement_status = "Ongoing"
			replicated_ticket.response_by = None
			replicated_ticket.response_by_variance = None
			replicated_ticket.resolution_by = None
			replicated_ticket.resolution_by_variance = None
			replicated_ticket.reset_ticket_metrics()

		frappe.get_doc(replicated_ticket).insert()

		# Replicate linked Communications
		# TODO: get all communications in timeline before this, and modify them to append them to new doc
		comm_to_split_from = frappe.get_doc("Communication", communication_id)
		communications = frappe.get_all(
			"Communication",
			filters={
				"reference_doctype": "HD Ticket",
				"reference_name": comm_to_split_from.reference_name,
				"creation": (">=", comm_to_split_from.creation),
			},
		)

		for communication in communications:
			doc = frappe.get_doc("Communication", communication.name)
			doc.reference_name = replicated_ticket.name
			doc.save(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": "HD Ticket",
				"reference_name": replicated_ticket.name,
				"content": (
					" - Split the Ticket from <a href='/app/Form/Ticket/{0}'>{1}</a>".format(
						self.name, frappe.bold(self.name)
					)
				),
			}
		).insert(ignore_permissions=True)

		return replicated_ticket.name

	def reset_ticket_metrics(self):
		self.db_set("resolution_time", None)
		self.db_set("user_resolution_time", None)

	@frappe.whitelist()
	def assign_agent(self, agent):
		if not agent:
			return

		if self._assign:
			assignees = json.loads(self._assign)
			for assignee in assignees:
				if agent == assignee:
					# the agent is already set as an assignee
					return

		clear_all_assignments("HD Ticket", self.name)
		assign({"assign_to": [agent], "doctype": "HD Ticket", "name": self.name})
		publish_event("helpdesk:ticket-assignee-update", {"name": self.name})

	def get_assigned_agent(self):
		# for some reason _assign is not set, maybe a framework bug?
		if hasattr(self, "_assign") and self._assign:
			assignees = json.loads(self._assign)
			if len(assignees) > 0:
				agent_doc = frappe.get_doc("HD Agent", assignees[0])
				return agent_doc

		from frappe.desk.form.assign_to import get

		assignees = get({"doctype": "HD Ticket", "name": self.name})
		if len(assignees) > 0:
			agent_doc = frappe.get_doc("HD Agent", assignees[0].owner)
			return agent_doc

		return None

	def on_trash(self):
		activities = frappe.db.get_all("HD Ticket Activity", {"ticket": self.name})
		for activity in activities:
			frappe.db.delete("HD Ticket Activity", activity)

	def skip_email_workflow(self):
		skip: str = frappe.get_value("HD Settings", None, "skip_email_workflow") or "0"

		return bool(int(skip))

	def instantly_send_email(self):
		check: str = (
			frappe.get_value("HD Settings", None, "instantly_send_email") or "0"
		)

		return bool(int(check))

	@frappe.whitelist()
	def get_last_communication(self):
		filters = {"reference_doctype": "HD Ticket", "reference_name": ["=", self.name]}

		try:
			communication = frappe.get_last_doc(
				"Communication",
				filters=filters,
			)

			return communication
		except Exception:
			pass

	def last_communication_email(self):
		if not (communication := self.get_last_communication()):
			return

		if not communication.email_account:
			return

		email_account = frappe.get_doc("Email Account", communication.email_account)

		if not email_account.enable_outgoing:
			return

		return email_account

	def sender_email(self):
		"""
		Find an email to use as sender. Fall back through multiple choices

		:return: `Email Account`
		"""
		if email_account := self.last_communication_email():
			return email_account

		if email_account := default_ticket_outgoing_email_account():
			return email_account

		if email_account := default_outgoing_email_account():
			return email_account

	@property
	def dashboard_uri(self):
		root_uri = frappe.utils.get_url()
		return f"{root_uri}/helpdesk/tickets/{self.name}"

	@property
	def portal_uri(self):
		root_uri = frappe.utils.get_url()
		return f"{root_uri}/helpdesk/my-tickets/{self.name}"

	@frappe.whitelist()
	def new_comment(self, content: str):
		if not is_agent():
			frappe.throw(
				_("You are not permitted to add a comment"), frappe.PermissionError
			)
		c = frappe.new_doc("HD Ticket Comment")
		c.commented_by = frappe.session.user
		c.content = content
		c.is_pinned = False
		c.reference_ticket = self.name
		c.save()

	@frappe.whitelist()
	def reply_via_agent(
		self, message: str, cc: str = None, bcc: str = None, attachments: List[str] = []
	):
		skip_email_workflow = self.skip_email_workflow()
		medium = "" if skip_email_workflow else "Email"
		subject = f"Re: {self.subject} (#{self.name})"
		sender = frappe.session.user
		recipients = self.raised_by
		sender_email = None if skip_email_workflow else self.sender_email()
		last_communication = self.get_last_communication()

		if last_communication:
			cc = cc or last_communication.cc
			bcc = bcc or last_communication.bcc

		if recipients == "Administrator":
			admin_email = frappe.get_value("User", "Administrator", "email")
			recipients = admin_email

		communication = frappe.get_doc(
			{
				"bcc": bcc,
				"cc": cc,
				"communication_medium": medium,
				"communication_type": "Communication",
				"content": message,
				"doctype": "Communication",
				"email_account": sender_email.name if sender_email else None,
				"email_status": "Open",
				"recipients": recipients,
				"reference_doctype": "HD Ticket",
				"reference_name": self.name,
				"sender": sender,
				"sent_or_received": "Sent",
				"status": "Linked",
				"subject": subject,
			}
		)

		communication.insert(ignore_permissions=True)

		# Mark status, unconditionally.
		self.reload()
		self.status = "Replied"
		self.save()

		capture_event("agent_replied")

		if skip_email_workflow:
			return

		if not sender_email:
			frappe.throw(_("Can not send email. No sender email set up!"))

		_attachments = []

		for attachment in attachments:
			file_doc = frappe.get_doc("File", attachment)
			file_doc.attached_to_name = communication.name
			file_doc.attached_to_doctype = "Communication"
			file_doc.save(ignore_permissions=True)
			_attachments.append({"file_url": file_doc.file_url})

		reply_to_email = sender_email.email_id
		template = (
			"new_reply_on_customer_portal_notification"
			if self.via_customer_portal
			else None
		)
		args = {
			"message": message,
			"portal_link": self.portal_uri,
			"ticket_id": self.name,
		}
		send_delayed = True
		send_now = False

		if self.instantly_send_email():
			send_delayed = False
			send_now = True

		try:
			frappe.sendmail(
				args=args,
				attachments=_attachments,
				bcc=bcc,
				cc=cc,
				communication=communication.name,
				delayed=send_delayed,
				expose_recipients="header",
				message=message,
				now=send_now,
				recipients=recipients,
				reference_doctype="HD Ticket",
				reference_name=self.name,
				reply_to=reply_to_email,
				sender=reply_to_email,
				subject=subject,
				template=template,
				with_container=False,
			)
		except Exception as e:
			frappe.throw(_(e))

	@frappe.whitelist()
	def create_communication_via_contact(self, message, attachments=[]):
		ticket_doc = frappe.get_doc("HD Ticket", self.name)

		if ticket_doc.status == "Replied":
			ticket_doc.status = "Open"
			log_ticket_activity(self.name, "set status to Open")
			ticket_doc.save(ignore_permissions=True)

		communication = frappe.new_doc("Communication")
		communication.update(
			{
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"email_status": "Open",
				"subject": "Re: " + ticket_doc.subject,
				"sender": frappe.session.user,
				"content": message,
				"status": "Linked",
				"reference_doctype": "HD Ticket",
				"reference_name": ticket_doc.name,
			}
		)
		communication.ignore_permissions = True
		communication.ignore_mandatory = True
		communication.save(ignore_permissions=True)

		for attachment in attachments:
			file_doc = frappe.get_doc("File", attachment)
			file_doc.attached_to_name = communication.name
			file_doc.attached_to_doctype = "Communication"
			file_doc.save(ignore_permissions=True)

	@frappe.whitelist()
	def mark_seen(self):
		self.add_view()
		self.add_seen()

	def add_view(self):
		d = frappe.new_doc("View Log")
		d.reference_doctype = "HD Ticket"
		d.reference_name = self.name
		d.viewed_by = frappe.session.user
		d.insert(ignore_permissions=True)

	@frappe.whitelist()
	def get_assignees(self):
		QBUser = DocType("User")
		assignees = frappe.parse_json(self._assign)

		if not assignees:
			return []

		condition = [QBUser.name == assignee for assignee in assignees]

		res = (
			frappe.qb.from_(QBUser)
			.select(QBUser.name, QBUser.full_name, QBUser.user_image)
			.where(Case.any(condition))
			.run(as_dict=True)
		)

		return res

	@frappe.whitelist()
	def get_communications(self):
		conversations = frappe.db.get_all(
			"Communication",
			filters={
				"reference_doctype": ["=", "HD Ticket"],
				"reference_name": ["=", self.name],
			},
			order_by="creation asc",
			fields=[
				"name",
				"content",
				"creation",
				"sent_or_received",
				"sender",
				"cc",
				"bcc",
			],
		)

		for conversation in conversations:
			if frappe.db.exists("HD Agent", conversation.sender):
				# user User details instead of Contact if the sender is an agent
				sender = frappe.get_doc("User", conversation.sender).__dict__
				sender["image"] = sender["user_image"]
			else:
				contacts = frappe.get_all(
					"Contact Email",
					filters=[["email_id", "like", "%{0}".format(conversation.sender)]],
					fields=["parent"],
					limit=1,
				)
				if len(contacts) > 0:
					sender = frappe.get_doc("Contact", contacts[0].parent)
				else:
					sender = frappe.get_last_doc(
						"User", filters={"email": conversation.sender}
					)

			conversation.sender = sender

			attachments = frappe.get_all(
				"File",
				["file_name", "file_url"],
				{
					"attached_to_name": conversation.name,
					"attached_to_doctype": "Communication",
				},
			)

			conversation.attachments = attachments

		return conversations

	def get_escalation_rule(self):
		filters = [
			{
				"priority": self.priority,
				"team": self.agent_group,
				"ticket_type": self.ticket_type,
			},
			{
				"priority": self.priority,
				"team": self.agent_group,
			},
			{
				"priority": self.priority,
				"ticket_type": self.ticket_type,
			},
			{
				"team": self.agent_group,
				"ticket_type": self.ticket_type,
			},
			{
				"priority": self.priority,
			},
			{
				"team": self.agent_group,
			},
			{
				"ticket_type": self.ticket_type,
			},
		]

		for i in range(len(filters)):
			try:
				f = {
					**filters[i],
					"is_enabled": True,
				}
				rule = frappe.get_last_doc("HD Escalation Rule", filters=f)
				if rule:
					return rule
			except Exception:
				pass

	@frappe.whitelist()
	def reopen(self):
		if self.status != "Resolved":
			frappe.throw(_("Only resolved tickets can be reopened"))

		if escalation_rule := self.get_escalation_rule():
			self.agent_group = escalation_rule.to_team or self.agent_group
			self.priority = escalation_rule.to_priority or self.priority
			self.ticket_type = escalation_rule.to_ticket_type or self.ticket_type
			self.assign_agent(escalation_rule.to_agent)

		self.status = "Open"
		self.save()

	@frappe.whitelist()
	def resolve(self):
		if self.status == "Closed":
			frappe.throw(_("Closed tickets cannot be resolved"))

		self.status = "Resolved"
		self.save()


def set_descritption_from_communication(doc, type):
	if doc.reference_doctype == "HD Ticket":
		ticket_doc = frappe.get_doc("HD Ticket", doc.reference_name)
		if not ticket_doc.via_customer_portal:
			ticket_doc.description = doc.content


@frappe.whitelist()
def create_communication_via_contact(ticket, message, attachments=[]):
	ticket_doc = frappe.get_doc("HD Ticket", ticket)

	if ticket_doc.status == "Replied":
		ticket_doc.status = "Open"
		log_ticket_activity(ticket, "set status to Open")
		ticket_doc.save(ignore_permissions=True)

	communication = frappe.new_doc("Communication")
	communication.update(
		{
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"email_status": "Open",
			"subject": "Re: " + ticket_doc.subject,
			"sender": ticket_doc.raised_by,
			"content": message,
			"status": "Linked",
			"reference_doctype": "HD Ticket",
			"reference_name": ticket_doc.name,
		}
	)
	communication.ignore_permissions = True
	communication.ignore_mandatory = True
	communication.save(ignore_permissions=True)

	for attachment in attachments:
		file_doc = frappe.get_doc("File", attachment)
		file_doc.attached_to_name = communication.name
		file_doc.attached_to_doctype = "Communication"
		file_doc.save(ignore_permissions=True)


@frappe.whitelist()
def update_ticket_status_via_customer_portal(ticket, new_status):
	ticket_doc = frappe.get_doc("HD Ticket", ticket)

	ticket_doc.status = new_status
	ticket_doc.save(ignore_permissions=True)

	return ticket_doc.status


@frappe.whitelist()
def get_all_conversations(ticket):
	conversations = frappe.db.get_all(
		"Communication",
		filters={
			"reference_doctype": ["=", "HD Ticket"],
			"reference_name": ["=", ticket],
		},
		order_by="creation asc",
		fields=[
			"name",
			"content",
			"creation",
			"sent_or_received",
			"sender",
			"cc",
			"bcc",
		],
	)

	for conversation in conversations:
		if frappe.db.exists("HD Agent", conversation.sender):
			# user User details instead of Contact if the sender is an agent
			sender = frappe.get_doc("User", conversation.sender).__dict__
			sender["image"] = sender["user_image"]
		else:
			contacts = frappe.get_all(
				"Contact Email",
				filters=[["email_id", "like", "%{0}".format(conversation.sender)]],
				fields=["parent"],
				limit=1,
			)
			if len(contacts) > 0:
				sender = frappe.get_doc("Contact", contacts[0].parent)
			else:
				sender = frappe.get_last_doc(
					"User", filters={"email": conversation.sender}
				)

		conversation.sender = sender

		attachments = frappe.get_all(
			"File",
			["file_name", "file_url"],
			{
				"attached_to_name": conversation.name,
				"attached_to_doctype": "Communication",
			},
		)

		conversation.attachments = attachments
	return conversations


@frappe.whitelist()
def get_all_attachments(ticket):
	attachments = frappe.get_all(
		"File",
		["file_name", "file_url"],
		{"attached_to_name": ticket, "attached_to_doctype": "HD Ticket"},
	)
	return attachments


def get_list_context(context=None):
	return {
		"title": _("Tickets"),
		"get_list": get_ticket_list,
		"row_template": "templates/includes/ticket_row.html",
		"show_sidebar": True,
		"show_search": True,
		"no_breadcrumbs": True,
	}


@frappe.whitelist()
def get_user_tickets(filters="{}", order_by="creation desc", impersonate=None):
	filters = json.loads(filters)
	filters["raised_by"] = ["=", frappe.session.user]

	if impersonate and frappe.db.exists("HD Agent", frappe.session.user):
		filters["raised_by"] = ["=", impersonate]

	tickets = frappe.get_all(
		"HD Ticket",
		filters=filters,
		order_by=order_by,
		fields=[
			"name",
			"subject",
			"description",
			"status",
			"creation",
			"feedback_submitted",
			"satisfaction_rating",
			"customer_feedback",
		],
	)
	return tickets


def get_ticket_list(
	doctype, txt, filters, limit_start, limit_page_length=20, order_by=None
):
	from frappe.www.list import get_list

	user = frappe.session.user
	contact = frappe.db.get_value("Contact", {"user": user}, "name")

	ignore_permissions = False
	if is_website_user():
		if not filters:
			filters = {}

		if contact:
			filters["contact"] = contact
		else:
			filters["raised_by"] = user

		ignore_permissions = True

	return get_list(
		doctype,
		txt,
		filters,
		limit_start,
		limit_page_length,
		ignore_permissions=ignore_permissions,
	)


@frappe.whitelist()
def set_multiple_status(names, status):

	for name in json.loads(names):
		frappe.db.set_value("HD Ticket", name, "status", status)


@frappe.whitelist()
def set_status(name, status):
	frappe.db.set_value("HD Ticket", name, "status", status)


def auto_close_tickets():
	"""Auto-close replied support tickets after 7 days"""
	auto_close_after_days = (
		frappe.db.get_value("HD Settings", "HD Settings", "close_ticket_after_days")
		or 7
	)

	tickets = frappe.db.sql(
		""" select name from `tabHD Ticket` where status='Replied' and
        modified<DATE_SUB(CURDATE(), INTERVAL %s DAY) """,
		(auto_close_after_days),
		as_dict=True,
	)

	for ticket in tickets:
		doc = frappe.get_doc("HD Ticket", ticket.get("name"))
		doc.status = "Closed"
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.save()


def has_website_permission(doc, ptype, user, verbose=False):
	# TODO: the commented code was used earilier, we dont need customers so just commented these out for now.
	# but will need to see if some more logic needs to be added here.
	# from erpnext.controllers.website_list_for_contact import has_website_permission
	# permission_based_on_customer = has_website_permission(doc, ptype, user, verbose)

	# return permission_based_on_customer or doc.raised_by==user
	return doc.raised_by == user


def update_ticket(contact, method):
	"""
	Called when Contact is deleted
	"""
	QBTicket = frappe.qb.DocType("HD Ticket")
	QBTicket.update().set(QBTicket.contact, "").where(QBTicket.contact == contact.name)


@frappe.whitelist()
def make_task(source_name, target_doc=None):
	return get_mapped_doc(
		"HD Ticket", source_name, {"HD Ticket": {"doctype": "Task"}}, target_doc
	)


@frappe.whitelist()
def make_ticket_from_communication(communication, ignore_communication_links=False):
	"""raise a ticket from email"""

	doc = frappe.get_doc("Communication", communication)
	ticket = frappe.get_doc(
		{
			"doctype": "HD Ticket",
			"subject": doc.subject,
			"communication_medium": doc.communication_medium,
			"raised_by": doc.sender or "",
			"raised_by_phone": doc.phone_no or "",
		}
	).insert(ignore_permissions=True)

	link_communication_to_document(
		doc, "HD Ticket", ticket.name, ignore_communication_links
	)

	return ticket.name


def get_time_in_timedelta(time):
	"""
	Converts datetime.time(10, 36, 55, 961454) to datetime.timedelta(seconds=38215)
	"""
	return timedelta(hours=time.hour, minutes=time.minute, seconds=time.second)


def set_first_response_time(communication, method):
	if communication.get("reference_doctype") == "HD Ticket":
		ticket = get_parent_doc(communication)
		if is_first_response(ticket) and ticket.sla:
			first_response_time = calculate_first_response_time(
				ticket, get_datetime(ticket.first_responded_on)
			)
			ticket.db_set("first_response_time", first_response_time)


def is_first_response(ticket):
	responses = frappe.get_all(
		"Communication",
		filters={"reference_name": ticket.name, "sent_or_received": "Sent"},
	)
	if len(responses) == 1:
		return True
	return False


def calculate_first_response_time(ticket, first_responded_on):
	ticket_creation_date = ticket.creation
	ticket_creation_time = get_time_in_seconds(ticket_creation_date)
	first_responded_on_in_seconds = get_time_in_seconds(first_responded_on)
	support_hours = frappe.get_cached_doc(
		"HD Service Level Agreement", ticket.sla
	).support_and_resolution

	if ticket_creation_date.day == first_responded_on.day:
		if is_work_day(ticket_creation_date, support_hours):
			start_time, end_time = get_working_hours(
				ticket_creation_date, support_hours
			)

			# ticket creation and response on the same day during working hours
			if is_during_working_hours(
				ticket_creation_date, support_hours
			) and is_during_working_hours(first_responded_on, support_hours):
				return get_elapsed_time(ticket_creation_date, first_responded_on)

			# ticket creation is during working hours, but first response was after working hours
			elif is_during_working_hours(ticket_creation_date, support_hours):
				return get_elapsed_time(ticket_creation_time, end_time)

			# ticket creation was before working hours but first response is during working hours
			elif is_during_working_hours(first_responded_on, support_hours):
				return get_elapsed_time(start_time, first_responded_on_in_seconds)

			# both ticket creation and first response were after working hours
			else:
				return 1.0  # this should ideally be zero, but it gets reset when the next response is sent if the value is zero

		else:
			return 1.0

	else:
		# response on the next day
		if date_diff(first_responded_on, ticket_creation_date) == 1:
			first_response_time = 0
		else:
			first_response_time = calculate_initial_frt(
				ticket_creation_date,
				date_diff(first_responded_on, ticket_creation_date) - 1,
				support_hours,
			)

		# time taken on day of ticket creation
		if is_work_day(ticket_creation_date, support_hours):
			start_time, end_time = get_working_hours(
				ticket_creation_date, support_hours
			)

			if is_during_working_hours(ticket_creation_date, support_hours):
				first_response_time += get_elapsed_time(ticket_creation_time, end_time)
			elif is_before_working_hours(ticket_creation_date, support_hours):
				first_response_time += get_elapsed_time(start_time, end_time)

		# time taken on day of first response
		if is_work_day(first_responded_on, support_hours):
			start_time, end_time = get_working_hours(first_responded_on, support_hours)

			if is_during_working_hours(first_responded_on, support_hours):
				first_response_time += get_elapsed_time(
					start_time, first_responded_on_in_seconds
				)
			elif not is_before_working_hours(first_responded_on, support_hours):
				first_response_time += get_elapsed_time(start_time, end_time)

		if first_response_time:
			return first_response_time
		else:
			return 1.0


def get_time_in_seconds(date):
	return timedelta(hours=date.hour, minutes=date.minute, seconds=date.second)


def get_working_hours(date, support_hours):
	if is_work_day(date, support_hours):
		weekday = frappe.utils.get_weekday(date)
		for day in support_hours:
			if day.workday == weekday:
				return day.start_time, day.end_time


def is_work_day(date, support_hours):
	weekday = frappe.utils.get_weekday(date)
	for day in support_hours:
		if day.workday == weekday:
			return True
	return False


def is_during_working_hours(date, support_hours):
	start_time, end_time = get_working_hours(date, support_hours)
	time = get_time_in_seconds(date)
	if time >= start_time and time <= end_time:
		return True
	return False


def get_elapsed_time(start_time, end_time):
	return round(time_diff_in_seconds(end_time, start_time), 2)


def calculate_initial_frt(ticket_creation_date, days_in_between, support_hours):
	initial_frt = 0
	for i in range(days_in_between):
		date = ticket_creation_date + timedelta(days=(i + 1))
		if is_work_day(date, support_hours):
			start_time, end_time = get_working_hours(date, support_hours)
			initial_frt += get_elapsed_time(start_time, end_time)

	return initial_frt


def is_before_working_hours(date, support_hours):
	start_time, end_time = get_working_hours(date, support_hours)
	time = get_time_in_seconds(date)
	if time < start_time:
		return True
	return False


def get_holidays(holiday_list_name):
	holiday_list = frappe.get_cached_doc("HD Service Holiday List", holiday_list_name)
	holidays = [holiday.holiday_date for holiday in holiday_list.holidays]
	return holidays
