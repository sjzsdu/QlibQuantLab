/**
 * 轻量 Markdown → HTML 渲染器（自研，避免引入重型 markdown 库）。
 *
 * 安全策略：先整体 HTML 转义，再做有限的 Markdown 语法替换，
 * 最终只输出经过转义的文本节点与固定的白名单标签，
 * 配合页面的 dangerouslySetInnerHTML 使用不会引入 XSS。
 * 支持：# ~ #### 标题、段落、换行、- / 1. 列表、**粗体**、*斜体*、`行内代码`、
 * ``` 代码块、> 引用、[文字](链接)（仅允许 http(s)/相对/锚点链接）。
 */

const SAFE_LINK = /^(https?:\/\/|\/(?!\/)|#)/;

/** HTML 转义（防注入的基础） */
export function escapeHtml(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** 行内语法（在已转义文本上替换） */
function renderInline(raw: string): string {
  let s = escapeHtml(raw);

  // `code`
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  // **bold**
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  // *italic*
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  // [text](url)
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_match, text: string, url: string) => {
    if (SAFE_LINK.test(url)) {
      return `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    }
    return `${text}（${escapeHtml(url)}）`;
  });

  return s;
}

/** 将 Markdown 文本渲染为安全的 HTML 字符串 */
export function renderMarkdown(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];

  let inCodeBlock = false;
  const codeLines: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let paragraph: string[] = [];

  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`);
      listType = null;
    }
  };

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      out.push(`<p>${paragraph.map(renderInline).join("<br/>")}</p>`);
      paragraph = [];
    }
  };

  const flushCodeBlock = () => {
    if (codeLines.length > 0 || inCodeBlock) {
      out.push(`<pre><code>${codeLines.join("\n")}</code></pre>`);
      codeLines.length = 0;
    }
  };

  for (const line of lines) {
    // 代码块围栏
    if (/^\s*```/.test(line)) {
      if (inCodeBlock) {
        flushCodeBlock();
        inCodeBlock = false;
      } else {
        flushParagraph();
        closeList();
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(escapeHtml(line));
      continue;
    }

    // 标题
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length;
      out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      continue;
    }

    // 引用
    const quote = /^>\s?(.*)$/.exec(line);
    if (quote) {
      flushParagraph();
      closeList();
      out.push(`<blockquote>${renderInline(quote[1])}</blockquote>`);
      continue;
    }

    // 列表
    const ul = /^\s*[-*]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+\.\s+(.*)$/.exec(line);
    if (ul || ol) {
      flushParagraph();
      const nextType: "ul" | "ol" = ul ? "ul" : "ol";
      if (listType && listType !== nextType) closeList();
      if (!listType) {
        listType = nextType;
        out.push(`<${listType}>`);
      }
      const item = (ul ?? ol)![1];
      out.push(`<li>${renderInline(item)}</li>`);
      continue;
    }

    // 空行：段落与列表边界
    if (line.trim() === "") {
      flushParagraph();
      closeList();
      continue;
    }

    paragraph.push(line);
  }

  if (inCodeBlock) {
    flushCodeBlock();
  }
  flushParagraph();
  closeList();

  return out.join("\n");
}
