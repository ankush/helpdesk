<template>
  <div class="flex flex-col overflow-hidden">
    <TopBar
      v-if="!isPublic"
      :back-to="backTo"
      :title="pageTitle"
      class="sticky top-0"
    >
      <template #right>
        <component
          :is="actionsComponent"
          :status="article.data?.status"
          @cancel="() => article.reload().then((editMode = !editMode))"
          @create="insertRes.submit"
          @delete="deleteRes.submit"
          @discard="router.push(backTo)"
          @save="updateContent"
          @toggle-edit-mode="editMode = !editMode"
          @toggle-status="toggleStatus"
        />
      </template>
    </TopBar>
    <div class="overflow-auto">
      <div class="m-auto mt-6 mb-12 rounded-xl" :style="containerStyle">
        <TextEditor
          :bubble-menu="true"
          :content="article.data?.content"
          :editable="editMode"
          :floating-menu="true"
          :placeholder="placeholder"
          class="rounded-xl px-6 py-4"
          editor-class="prose prose-sm prose-img:rounded prose-img:border max-w-none my-4"
          @change="articleContent = $event"
        >
          <template #top>
            <component
              :is="topComponent"
              v-model:title="articleTitle"
              v-bind="options__"
            />
          </template>
        </TextEditor>
        <div class="flex flex-col gap-2 px-6">
          <div class="text-base font-medium">Still need help?</div>
          <RouterLink :to="{ name: CUSTOMER_PORTAL_NEW_TICKET }">
            <Button
              label="Create a ticket"
              size="md"
              theme="gray"
              variant="solid"
            />
          </RouterLink>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  createResource,
  createDocumentResource,
  debounce,
  Button,
  TextEditor,
} from "frappe-ui";
import {
  AGENT_PORTAL_KNOWLEDGE_BASE_SUB_CATEGORY,
  AGENT_PORTAL_KNOWLEDGE_BASE_ARTICLE,
  CUSTOMER_PORTAL_NEW_TICKET,
} from "@/router";
import { createToast } from "@/utils/toasts";
import { useAuthStore } from "@/stores/auth";
import TopBar from "@/components/TopBar.vue";
import KnowledgeBaseArticleActionsEdit from "./KnowledgeBaseArticleActionsEdit.vue";
import KnowledgeBaseArticleActionsNew from "./KnowledgeBaseArticleActionsNew.vue";
import KnowledgeBaseArticleActionsView from "./KnowledgeBaseArticleActionsView.vue";
import KnowledgeBaseArticleTopEdit from "./KnowledgeBaseArticleTopEdit.vue";
import KnowledgeBaseArticleTopNew from "./KnowledgeBaseArticleTopNew.vue";
import KnowledgeBaseArticleTopPublic from "./KnowledgeBaseArticleTopPublic.vue";
import KnowledgeBaseArticleTopView from "./KnowledgeBaseArticleTopView.vue";

const props = defineProps({
  articleId: {
    type: String,
    required: true,
  },
  isPublic: {
    type: Boolean,
    required: false,
    default: false,
  },
});

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const isNew = props.articleId.toLowerCase() === "new";
const editMode = ref(isNew);
const categoryId = computed(
  () => article.data?.category.name || route.query.category
);
const subCategoryId = computed(
  () => article.data?.sub_category.name || route.query.subCategory
);
const pageTitle = computed(() => article.data?.title || "New article");
const placeholder = computed(() =>
  editMode.value ? "Write something..." : "Content is empty"
);
const articleContent = ref("");
const articleTitle = ref("");

const actionsComponent = computed(() => {
  if (isNew) return KnowledgeBaseArticleActionsNew;
  if (editMode.value) return KnowledgeBaseArticleActionsEdit;
  return KnowledgeBaseArticleActionsView;
});

const topComponent = computed(() => {
  if (props.isPublic) return KnowledgeBaseArticleTopPublic;
  if (isNew) return KnowledgeBaseArticleTopNew;
  if (editMode.value) return KnowledgeBaseArticleTopEdit;
  return KnowledgeBaseArticleTopView;
});

const article = createResource({
  url: "helpdesk.helpdesk.doctype.hd_article.api.get_article",
  params: {
    name: props.articleId,
  },
  auto: !isNew,
});

const category = createDocumentResource({
  doctype: "HD Article Category",
  name: categoryId.value,
  auto: !!route.query.category,
});

const subCategory = createDocumentResource({
  doctype: "HD Article Category",
  name: subCategoryId.value,
  auto: !!route.query.subCategory,
});

const options__ = computed(() => ({
  authorFullname: article.data?.author.full_name || authStore.userName,
  authorImage: article.data?.author.user_image || authStore.userImage,
  categoryId: categoryId.value,
  categoryName:
    article.data?.category.category_name || category?.doc?.category_name,
  creation: article.data?.creation,
  dislikes: article.data?.not_helpful,
  likes: article.data?.helpful,
  modified: article.data?.modified,
  status: article.data?.status,
  subCategoryId: subCategoryId.value,
  subCategoryName:
    article.data?.sub_category.category_name || subCategory?.doc?.category_name,
  title: article.data?.title,
}));

const insertRes = createResource({
  url: "frappe.client.insert",
  makeParams() {
    return {
      doc: {
        doctype: "HD Article",
        category: categoryId.value,
        title: articleTitle.value,
        content: articleContent.value,
      },
    };
  },
  validate(params) {
    if (!params.doc.title) throw "Title is required";
    if (!params.doc.content) throw "Content is required";
  },
  onSuccess(data) {
    router
      .push({
        name: AGENT_PORTAL_KNOWLEDGE_BASE_ARTICLE,
        params: {
          articleId: data.name,
        },
      })
      .then(() => router.go(0));
  },
  onError(error) {
    const msg = error.message ? error.message : error.messages.join(", ");
    createToast({
      title: "Error renaming team",
      text: msg,
      icon: "x",
      iconClasses: "text-red-500",
    });
  },
});

const setValueRes = createResource({
  url: "frappe.client.set_value",
  onSuccess() {
    article.reload();
    createToast({
      title: "Article updated",
      icon: "check",
      iconClasses: "text-green-500",
    });
  },
  onError(error) {
    const msg = error.messages.join(", ");
    createToast({
      title: "Error updating article",
      text: msg,
      icon: "x",
      iconClasses: "text-red-500",
    });
  },
});

const deleteRes = createResource({
  url: "frappe.client.delete",
  makeParams() {
    return {
      doctype: "HD Article",
      name: props.articleId,
    };
  },
  onSuccess() {
    router.replace(backTo.value);
  },
});

const updateContent = debounce(() => {
  setValueRes.submit({
    doctype: "HD Article",
    name: article.data.name,
    fieldname: {
      content: articleContent.value,
      title: articleTitle.value,
    },
  });
}, 300);

const toggleStatus = debounce(() => {
  const status = article.data.status === "Published" ? "Draft" : "Published";
  setValueRes.submit({
    doctype: "HD Article",
    name: article.data.name,
    fieldname: "status",
    value: status,
  });
}, 300);

const backTo = computed(() => ({
  name: AGENT_PORTAL_KNOWLEDGE_BASE_SUB_CATEGORY,
  params: {
    categoryId: categoryId.value,
    subCategoryId: subCategoryId.value,
  },
}));

const containerStyle = computed(() => ({
  width: "790px",
  "box-shadow": editMode.value
    ? "0px 1px 2px 0px rgba(0, 0, 0, 0.1), 0px 0px 1px 0px rgba(0, 0, 0, 0.45)"
    : "",
}));
</script>
