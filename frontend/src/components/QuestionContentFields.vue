<script setup>
import { questionLabels } from '../utils/answerFlow.js'
const props = defineProps({ content: { type: Object, required: true }, disabled: Boolean })
function changeType() {
  props.content.options = ['single', 'multiple'].includes(props.content.type) ? [{ label: '' }, { label: '' }] : []
  props.content.validation = props.content.type === 'number' ? { integer_only: false, phone_format: false } : {}
}
</script>

<template>
  <fieldset :disabled="disabled" class="editor-fieldset form-stack">
    <label>题型<select v-model="content.type" @change="changeType"><option v-for="(label, type) in questionLabels" :key="type" :value="type">{{ label }}</option></select></label>
    <label>题干<input v-model="content.title" required maxlength="200" /></label>
    <template v-if="['single', 'multiple'].includes(content.type)">
      <div v-for="(option, index) in content.options" :key="index" class="editor-row option-row">
        <label>选项 {{ index + 1 }}<input v-model="option.label" required maxlength="100" /></label>
        <button v-if="!disabled" type="button" class="text-button danger-text" :disabled="content.options.length <= 2" @click="content.options.splice(index, 1)">删除选项</button>
      </div>
      <button v-if="!disabled" type="button" class="button secondary" :disabled="content.options.length >= 30" @click="content.options.push({ label: '' })">添加选项</button>
    </template>
    <div class="validation-grid">
      <template v-if="content.type === 'multiple'">
        <label>最少选择<input v-model.number="content.validation.min_choices" type="number" min="0" :max="content.options.length" /></label>
        <label>最多选择<input v-model.number="content.validation.max_choices" type="number" min="0" :max="content.options.length" /></label>
      </template>
      <template v-if="content.type === 'text'">
        <label>最少字符<input v-model.number="content.validation.min_length" type="number" min="0" /></label>
        <label>最多字符<input v-model.number="content.validation.max_length" type="number" min="0" /></label>
      </template>
      <template v-if="content.type === 'number'">
        <label>最小值<input v-model.number="content.validation.min_value" type="number" step="any" /></label>
        <label>最大值<input v-model.number="content.validation.max_value" type="number" step="any" /></label>
        <label class="check-label"><input v-model="content.validation.integer_only" type="checkbox" :disabled="disabled || content.validation.phone_format" />仅允许整数</label>
        <label class="check-label"><input v-model="content.validation.phone_format" type="checkbox" @change="content.validation.phone_format && (content.validation.integer_only = true)" />校验11位手机号格式</label>
      </template>
    </div>
  </fieldset>
</template>
