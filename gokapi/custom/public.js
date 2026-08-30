// Translates Gokapi's public-facing pages (download, password prompt) to
// Simplified Chinese. Loaded automatically by Gokapi if this file exists at
// custom/public.js — no server rebuild needed. Extend the dictionaries below
// for any other public-facing string that needs translating.
(function () {
  var textMap = {
    "Download": "下载",
    "Download File": "下载文件",
    "Loading...": "加载中...",
    "Decrypting...": "解密中...",
    "Encrypted": "已加密",
    "Size": "大小",
    "Password required": "需要密码",
    "Incorrect password!": "密码错误！",
    "Continue": "继续"
  };
  var placeholderMap = {
    "Enter password": "请输入密码"
  };

  function translateNode(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      var trimmed = node.nodeValue.trim();
      if (Object.prototype.hasOwnProperty.call(textMap, trimmed)) {
        node.nodeValue = node.nodeValue.replace(trimmed, textMap[trimmed]);
      }
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.placeholder && Object.prototype.hasOwnProperty.call(placeholderMap, node.placeholder)) {
      node.placeholder = placeholderMap[node.placeholder];
    }
    node.childNodes.forEach(translateNode);
  }

  function translateAll() {
    translateNode(document.body);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", translateAll);
  } else {
    translateAll();
  }

  // Some text (e.g. "Loading..." -> "Download File" once WASM is ready)
  // changes after the initial render, so keep watching for it.
  new MutationObserver(function (mutations) {
    mutations.forEach(function (m) {
      m.addedNodes.forEach(translateNode);
      if (m.type === "characterData") translateNode(m.target);
    });
  }).observe(document.body, { childList: true, subtree: true, characterData: true });
})();
