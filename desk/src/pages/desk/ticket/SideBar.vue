<template>
  <div class="flex">
    <TabGroup vertical>
      <TabPanels v-if="sidebar.isExpanded" class="main-panel h-full">
        <TabPanel v-for="item in items" :key="item.name" class="h-full">
          <component :is="item.component" class="h-full" />
        </TabPanel>
      </TabPanels>
      <TabList class="sidebar flex flex-col gap-2 border-l">
        <Tab v-for="item in items" :key="item.name" v-slot="{ selected }">
          <div
            class="flex h-7 w-7 items-center justify-center rounded-lg text-gray-600"
            :class="{
              'bg-gray-200': sidebar.isExpanded && selected,
              'text-gray-900': sidebar.isExpanded && selected,
            }"
            @click="sidebar.isExpanded = true"
          >
            <Icon :icon="item.icon" class="h-4 w-4" />
          </div>
        </Tab>
      </TabList>
    </TabGroup>
  </div>
</template>

<script setup lang="ts">
import { TabGroup, TabList, Tab, TabPanels, TabPanel } from "@headlessui/vue";
import { Icon } from "@iconify/vue";
import { useTicketStore } from "./data";
import ContactDetails from "./ContactDetails.vue";
import TicketDetails from "./TicketDetails.vue";
import TicketHistory from "./TicketHistory.vue";

const { sidebar } = useTicketStore();
const items = [
  {
    name: "Ticket Details",
    component: TicketDetails,
    icon: "lucide:info",
  },
  {
    name: "Contact Details",
    component: ContactDetails,
    icon: "lucide:contact-2",
  },
  {
    name: "Ticket History",
    component: TicketHistory,
    icon: "lucide:history",
  },
];
</script>

<style scoped>
.main-panel {
  width: 310px;
}

.sidebar {
  width: 50px;
  padding: 16px 12px 0 10px;
}

.icon {
  height: 18px;
  width: 18px;
}
</style>
