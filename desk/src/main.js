import { createApp, ref } from 'vue'
import { FrappeUI, Button } from 'frappe-ui'
import router from './router'
import App from './App.vue'
import './index.css'
import { dayjs } from '@/utils'

let app = createApp(App)
app.use(router)
app.use(FrappeUI)
app.component('Button', Button)

app.config.globalProperties.$dayjs = dayjs

const globalVariables = ref({
	user: null,

	tickets: {},
	ticketTypes: null,
	ticketPriorities: null,
	ticketStatuses: null,
	contacts: {},
	updateTickets: () => {},
	updateTicket: (ticketId) => {},
	assignAgent: (ticketId, agentName) => {},
	assignType: (ticketId, type) => {},
	assignStatus: (ticketId, status) => {},
	assignPriority: (ticketId, priority) => {},

	createTicket: (values) => {},
	updateContact: (contactId) => {},
	createContact: (emailId, fullName) => {},

	createType: (type) => {},

	ticketFilter: "All Tickets",
	contactFilter: "All Contacts",

	agents: null,

	currentPage: "Tickets"	// Tickets, Ticket, Contacts, ...
})

app.config.globalProperties.$user = {
	set(newValue) {
		globalVariables.value.user = newValue;
	},
	get() {
		return globalVariables.value.user;
	}
};

app.config.globalProperties.$tickets = (ticketId) => {
	return {
		update: () => {
			if (ticketId) {
				globalVariables.value.updateTicket(ticketId)
			} else {
				globalVariables.value.updateTickets()
			}
		},
		set: (value) => {
			if (ticketId) {
				globalVariables.value.tickets[ticketId] = value;
			} else {
				if ("types" in value) {
					globalVariables.value.ticketTypes = value.types.map(x => x.name)
				}
				if ("statuses" in value) {
					globalVariables.value.ticketStatuses = value.statuses
				}
				if ("priorities" in value) {
					globalVariables.value.ticketPriorities = value.priorities.map(x => x.name)
				}
				if ("tickets" in value) {
					for (var i = 0; i < value.tickets.length; i++) {
						globalVariables.value.tickets[value.tickets[i].name] = value.tickets[i];
					}
				}
				if ("contacts" in value) {
					globalVariables.value.contacts = value.contacts.map(x => x.name)
				}
			}
		},
		get: (valueType=null) => {
			if (ticketId) {
				return (ticketId in globalVariables.value.tickets) ? globalVariables.value.tickets[ticketId] : null
			}
			switch(valueType) {
				case "types":
					return globalVariables.value.ticketTypes
				case "priorities":
					return globalVariables.value.ticketPriorities
				case "statuses":
					return globalVariables.value.ticketStatuses
				case "contacts":
					return globalVariables.value.contacts
				default:
					return globalVariables.value.tickets
			}
		},
		createTicket: (values) => {
			globalVariables.value.createTicket(values)
		},
		assignAgent: (agentName) => {
			globalVariables.value.assignAgent(ticketId, agentName)
		},
		assignType: (type) => {
			globalVariables.value.assignType(ticketId, type)
		},
		assignStatus: (status) => {
			globalVariables.value.assignStatus(ticketId, status)
		},
		assignPriority: (priority) => {
			globalVariables.value.assignPriority(ticketId, priority)
		},
		createType: (type) => {
			globalVariables.value.createType(type)
		},
		updateContact: (contactId) => {
			globalVariables.value.updateContact(ticketId, contactId)
		},
		setUpdateTicket: (foo) => {
			globalVariables.value.updateTicket = foo
		},
		setUpdateTickets: (foo) => {
			globalVariables.value.updateTickets = foo
		},
		setCreateTicket: (foo) => {
			globalVariables.value.createTicket = foo
		},
		setAssignAgent: (foo) => {
			globalVariables.value.assignAgent = foo
		},
		setAssignType: (foo) => {
			globalVariables.value.assignType = foo
		},
		setAssignStatus: (foo) => {
			globalVariables.value.assignStatus = foo
		},
		setAssignPriority: (foo) => {
			globalVariables.value.assignPriority = foo
		},
		setCreateType: (foo) => {
			globalVariables.value.createType = foo
		},
		setUpdateContact: (foo) => {
			globalVariables.value.updateContact = foo
		}
	}
}

app.config.globalProperties.$agents = {
	set(newValue) {
		globalVariables.value.agents = newValue;
	},
	get() {
		return globalVariables.value.agents;
	},
	update: () => {}
}

app.config.globalProperties.$ticketFilter = {
	set(newValue) { 
		globalVariables.value.ticketFilter= newValue;
	},
	get() {
		return globalVariables.value.ticketFilter;
	}
};

app.config.globalProperties.$contactFilter = {
	set(newValue) { 
		globalVariables.value.contactFilter= newValue;
	},
	get() {
		return globalVariables.value.contactFilter;
	}
};

app.config.globalProperties.$currentPage = {
	set(newValue) { 
		globalVariables.value.currentPage= newValue;
	},
	get() {
		return globalVariables.value.currentPage;
	}
};

app.mount('#app')