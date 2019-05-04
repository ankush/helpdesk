# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from frappe import _

class ServiceLevelAgreement(Document):

	def validate(self):
		if not (self.customer or self.default_service_level_agreement):
			frappe.throw(_("Select a Customer or set as Default Service Level Agreement."))

		if self.default_service_level_agreement:
			if frappe.db.exists("Service Level Agreement", {"default_service_level_agreement": "1"}):
				frappe.throw(_("A Default Service Level Agreement already exists."))
		else:
			if not (self.start_date and self.end_date):
				frappe.throw(_("Enter Start and End Date for the Agreement."))
			if self.start_date >= self.end_date:
				frappe.throw(_("Start Date of Agreement can't be greater than or equal to End Date."))
			if self.end_date < frappe.utils.getdate():
				frappe.throw(_("End Date of Agreement can't be less than today."))

def check_agreement_status():
	service_level_agreements = frappe.get_list("Service Level Agreement", filters=[
		{"agreement_status": "Active"},
		{"default_service_level_agreement": 0}
	])
	service_level_agreements.reverse()
	for service_level_agreement in service_level_agreements:
		service_level_agreement = frappe.get_doc("Service Level Agreement", service_level_agreement)
		if service_level_agreement.end_date < frappe.utils.getdate():
			service_level_agreement.agreement_status = "Expired"
		service_level_agreement.save()

@frappe.whitelist()
def get_active_service_level_agreement_for(customer, priority):

	agreement = frappe.db.sql("""
			select `tabService Level Agreement`.name, `tabService Level Agreement`.service_level,
			`tabService Level Agreement`.holiday_list
			from `tabService Level Agreement`
			inner join `tabService Level Priority`
			on `tabService Level Agreement`.name=`tabService Level Priority`.parent where
			(
				`tabService Level Agreement`.customer='{0}' and
				`tabService Level Agreement`.agreement_status='Active' and
				`tabService Level Priority`.priority='{1}'
			) or
			(
				`tabService Level Agreement`.default_service_level_agreement='1'
			)
			 limit 1
		""".format(customer, priority), as_dict=True, debug=True)

	print(agreement)

	return agreement[0] if agreement else None