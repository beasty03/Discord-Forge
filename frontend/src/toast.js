export function toast(text, type = 'success') {
  window.dispatchEvent(new CustomEvent('df:toast', { detail: { text, type } }));
}
