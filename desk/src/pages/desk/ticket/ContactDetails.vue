<template>
  <div class="flex flex-col border-l">
    <div class="mx-4 mt-4">
      <div class="flex items-center justify-between">
        <div class="text-lg font-semibold text-gray-800">Contact details</div>
        <Button
          icon="x"
          theme="gray"
          variant="ghost"
          @click="sidebar.isExpanded = false"
        />
      </div>
      <div class="flex items-center gap-3 border-b py-6">
        <Avatar :image="contact.image" :label="contact.full_name" size="lg" />
        <div class="flex flex-col">
          <div class="text-lg font-semibold text-gray-800">
            {{ contact.full_name }}
          </div>
          <div class="text-base text-gray-600">
            {{ contact.company_name }}
          </div>
        </div>
      </div>
    </div>
    <div class="overflow-auto px-4">
      <div
        v-if="!isEmpty(contactOptions)"
        class="flex flex-col gap-3.5 border-b py-6 text-base"
      >
        <div
          v-for="c in contactOptions"
          :key="c.name"
          class="flex items-start gap-2"
        >
          <div class="h-5 w-5">
            <Icon :icon="c.icon" class="h-4 w-4 text-gray-600" />
          </div>
          <div class="text-gray-900">{{ c.value }}</div>
        </div>
      </div>
      <CustomFieldList />
      <OpenTicketList />
    </div>
  </div>
</template>

<script setup lang="ts">
import { isEmpty } from "lodash";
import { computed } from "vue";
import { Avatar, Button } from "frappe-ui";
import { Icon } from "@iconify/vue";
import CustomFieldList from "./CustomFieldList.vue";
import OpenTicketList from "./OpenTicketList.vue";
import { useTicketStore, useTicket } from "./data";

const fields = [
  {
    field: "email_id",
    icon: "lucide:mail",
  },
  {
    field: "phone",
    icon: "lucide:phone",
  },
  {
    field: "mobile_no",
    icon: "lucide:smartphone",
  },
];

const { sidebar } = useTicketStore();
const ticket = useTicket();
const contact = computed(() => ticket.value.data.contact);
const contactOptions = computed(() =>
  fields
    .map((o) => ({
      name: o.field,
      value: contact.value[o.field],
      icon: o.icon,
    }))
    .filter((o) => o.value)
);
</script>
