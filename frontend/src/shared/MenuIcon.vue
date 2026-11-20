<script setup>
defineProps({open:Boolean})
</script>
<template><span class="animated-menu-icon" :class="{opened:open}" aria-hidden="true"><span></span><span></span><span></span></span></template>
<style scoped>
.animated-menu-icon { position:relative; display:inline-block; width:20px; height:20px; flex:none; }
.animated-menu-icon span { position:absolute; left:2px; width:16px; height:1.6px; border-radius:2px; background:currentColor; transition:transform .22s cubic-bezier(.2,.8,.2,1),opacity .15s,width .22s; }
.animated-menu-icon span:nth-child(1) { top:4px; }.animated-menu-icon span:nth-child(2) { top:9px; width:12px; }.animated-menu-icon span:nth-child(3) { top:14px; }
.opened span:nth-child(1) { transform:translateY(5px) rotate(45deg); }.opened span:nth-child(2) { opacity:0;transform:translateX(4px); }.opened span:nth-child(3) { transform:translateY(-5px) rotate(-45deg); }
@media(prefers-reduced-motion:reduce) { .animated-menu-icon span {transition:none;} }
</style>
