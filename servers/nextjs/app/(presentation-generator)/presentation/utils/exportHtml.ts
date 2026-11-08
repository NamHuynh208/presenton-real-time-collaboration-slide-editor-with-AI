// Client-side "Export as HTML": one self-contained file, each slide in an <iframe srcdoc>
// so per-slide styles and Chart.js runtimes stay isolated.
import {
  TEMPLATE_V2_HTML_HEIGHT as H,
  TEMPLATE_V2_HTML_WIDTH as W,
  templateV2UiToHtml,
} from "@/lib/template-v2-json-to-html";
import { shouldRenderTemplateV2HtmlPreview } from "@/app/(presentation-generator)/components/TemplateV2HtmlSlidePreview";

type PresentationLike = {
  title?: unknown;
  version?: unknown;
  fonts?: unknown;
  slides?: unknown[];
};

const escapeHtml = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// Google Fonts CSS stays a link (it serves per-browser font files); everything else gets inlined.
const shouldInline = (url: string) =>
  !!url &&
  !/^(data:|blob:|#|javascript:|mailto:)/i.test(url) &&
  !/fonts\.(googleapis|gstatic)\.com/i.test(url);

const absolute = (url: string) => {
  try {
    return new URL(url, window.location.origin).href;
  } catch {
    return url;
  }
};

const cache = new Map<string, Promise<string>>();

function toDataUri(url: string): Promise<string> {
  const abs = absolute(url);
  if (!cache.has(abs)) {
    cache.set(
      abs,
      fetch(abs, { credentials: "include" })
        .then((r) => {
          if (!r.ok) throw new Error(String(r.status));
          return r.blob();
        })
        .then(
          (blob) =>
            new Promise<string>((resolve, reject) => {
              const reader = new FileReader();
              reader.onload = () => resolve(String(reader.result));
              reader.onerror = () => reject(reader.error);
              reader.readAsDataURL(blob);
            }),
        )
        .catch((error) => {
          console.warn("[export-html] could not inline asset, keeping absolute URL", abs, error);
          return abs;
        }),
    );
  }
  return cache.get(abs)!;
}

const scriptCache = new Map<string, Promise<string | null>>();
function fetchScript(url: string) {
  const abs = absolute(url);
  if (!scriptCache.has(abs)) {
    scriptCache.set(
      abs,
      fetch(abs, { credentials: "include" })
        .then((r) => (r.ok ? r.text() : null))
        .catch(() => null),
    );
  }
  return scriptCache.get(abs)!;
}

async function replaceAsync(
  input: string,
  re: RegExp,
  fn: (...m: string[]) => Promise<string>,
): Promise<string> {
  const matches = Array.from(input.matchAll(re));
  const replacements = await Promise.all(matches.map((m) => fn(...(m as unknown as string[]))));
  let out = "";
  let last = 0;
  matches.forEach((m, i) => {
    out += input.slice(last, m.index) + replacements[i];
    last = (m.index ?? 0) + m[0].length;
  });
  return out + input.slice(last);
}

/** Inline external scripts, <img src>, <link href> (non-Google-Fonts) and CSS url(...) as data. */
export async function inlineAssets(html: string): Promise<string> {
  let out = html;
  const inlineAttrs = (attrRe: RegExp) => (tag: string) =>
    replaceAsync(tag, attrRe, async (whole, attr, q, url) => {
      const decoded = url.replace(/&amp;/g, "&");
      if (!shouldInline(decoded)) return whole;
      return ` ${attr}=${q}${await toDataUri(decoded)}${q}`;
    });
  // <a href> stays a link; only media src/poster and <link href> are inlined.
  out = await replaceAsync(
    out,
    /<(?:img|source|video|audio|image|input)\b[^>]*>/gi,
    inlineAttrs(/\s(src|poster|href|xlink:href)=(["'])([^"']*)\2/gi),
  );
  out = await replaceAsync(out, /<link\b[^>]*>/gi, inlineAttrs(/\s(href)=(["'])([^"']*)\2/gi));
  out = await replaceAsync(out, /url\(\s*(["']?)([^"')]+)\1\s*\)/gi, async (whole, q, url) => {
    const decoded = url.replace(/&amp;/g, "&").replace(/&quot;/g, "");
    if (!shouldInline(decoded)) return whole;
    // Single quotes: the url() may sit inside a style="..." attribute.
    return `url('${await toDataUri(decoded)}')`;
  });
  // Scripts last, so the url()/tag passes never touch library code.
  out = await replaceAsync(
    out,
    /<script\b([^>]*?)\bsrc=["']([^"']+)["']([^>]*)><\/script>/gi,
    async (whole, _a, src) => {
      const code = await fetchScript(src);
      return code == null
        ? whole.replace(src, absolute(src))
        : `<script>${code.replace(/<\/script/gi, "<\\/script")}</script>`;
    },
  );
  return out;
}

function placeholderDoc(index: number) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;height:100%}body{display:flex;align-items:center;justify-content:center;font:24px system-ui,sans-serif;color:#666;background:#f3f4f6}</style></head><body>Slide ${index + 1} cannot be exported to HTML (legacy layout). Use PDF/PPTX export.</body></html>`;
}

/** Per slide: TemplateV2 UI → HTML; else saved html_content; else a placeholder (warned in console). */
export function slideToHtmlDocument(slide: unknown, index: number, data: PresentationLike): string {
  if (shouldRenderTemplateV2HtmlPreview(slide, data.version)) {
    const doc = templateV2UiToHtml((slide as { ui: unknown }).ui, {
      fonts: data.fonts as never,
    });
    if (doc) return doc;
  }
  const htmlContent = (slide as { html_content?: unknown } | null)?.html_content;
  if (typeof htmlContent === "string" && htmlContent.trim()) {
    return /<html[\s>]/i.test(htmlContent)
      ? htmlContent
      : `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;width:${W}px;height:${H}px;overflow:hidden}</style></head><body>${htmlContent}</body></html>`;
  }
  console.warn(`[export-html] slide ${index + 1} has no TemplateV2 ui or html_content; exporting a placeholder.`);
  return placeholderDoc(index);
}

export function buildDeckHtml(title: string, slideDocs: string[]): string {
  const frames = slideDocs
    .map(
      (doc, i) =>
        `<section class="slide" data-index="${i}"><iframe title="Slide ${i + 1}" width="${W}" height="${H}" srcdoc="${escapeHtml(doc)}"></iframe></section>`,
    )
    .join("\n");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>
html,body{margin:0;height:100%;background:#111;overflow:hidden;font-family:system-ui,sans-serif}
#stage{position:fixed;inset:0;display:flex;align-items:center;justify-content:center}
#deck{width:${W}px;height:${H}px;position:relative;flex:none;transform-origin:center center}
.slide{position:absolute;inset:0;display:none;background:#fff}
.slide.active{display:block}
.slide iframe{border:0;display:block;width:${W}px;height:${H}px;pointer-events:auto}
#bar{position:fixed;right:16px;bottom:12px;display:flex;gap:8px;align-items:center;color:#ddd;font-size:14px;z-index:2;opacity:.7}
#bar:hover{opacity:1}
#bar button{background:#333;color:#eee;border:0;border-radius:6px;padding:6px 10px;cursor:pointer;font:inherit}
@page{size:${W}px ${H}px;margin:0}
@media print{
  html,body{background:#fff;overflow:visible;height:auto}
  #stage{position:static;display:block}
  #deck{transform:none!important;width:auto;height:auto}
  .slide{display:block!important;position:relative;width:${W}px;height:${H}px;page-break-after:always;break-after:page;overflow:hidden}
  #bar{display:none}
}
</style></head>
<body>
<div id="stage"><div id="deck">
${frames}
</div></div>
<div id="bar"><button id="prev" aria-label="Previous slide">&larr;</button><span id="counter"></span><button id="next" aria-label="Next slide">&rarr;</button><button id="fs" aria-label="Fullscreen">F</button></div>
<script>
(function(){
  var slides=[].slice.call(document.querySelectorAll('.slide'));
  var deck=document.getElementById('deck'), counter=document.getElementById('counter'), i=0;
  function fit(){var s=Math.min(innerWidth/${W},innerHeight/${H});deck.style.transform='scale('+s+')';}
  function show(n){if(!slides.length)return;i=Math.max(0,Math.min(slides.length-1,n));
    slides.forEach(function(el,k){el.classList.toggle('active',k===i);});
    counter.textContent=(i+1)+' / '+slides.length;}
  function fs(){if(document.fullscreenElement)document.exitFullscreen();else document.documentElement.requestFullscreen&&document.documentElement.requestFullscreen();}
  function key(e){var k=e.key;
    if(k==='ArrowRight'||k==='ArrowDown'||k===' '||k==='PageDown'){e.preventDefault();show(i+1);}
    else if(k==='ArrowLeft'||k==='ArrowUp'||k==='PageUp'){e.preventDefault();show(i-1);}
    else if(k==='Home'){show(0);}else if(k==='End'){show(slides.length-1);}
    else if(k==='f'||k==='F'){fs();}}
  document.addEventListener('keydown',key);
  // Keys pressed while an iframe has focus still navigate.
  slides.forEach(function(el){var f=el.querySelector('iframe');f.addEventListener('load',function(){try{f.contentWindow.document.addEventListener('keydown',key);}catch(_){}});});
  document.getElementById('prev').onclick=function(){show(i-1);};
  document.getElementById('next').onclick=function(){show(i+1);};
  document.getElementById('fs').onclick=fs;
  addEventListener('resize',fit);fit();show(0);
})();
</script>
</body></html>`;
}

export function safeHtmlFileName(rawTitle: unknown) {
  const base =
    String(rawTitle ?? "")
      .replace(/\.html?$/i, "")
      .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 120) || "presentation";
  return `${base}.html`;
}

/** Build the full deck HTML (assets inlined) for the given presentation. */
export async function buildPresentationHtml(data: PresentationLike): Promise<string> {
  const slides = Array.isArray(data.slides) ? data.slides : [];
  const docs = await Promise.all(
    slides.map((slide, i) => inlineAssets(slideToHtmlDocument(slide, i, data))),
  );
  return buildDeckHtml(String(data.title || "Presentation"), docs);
}

export async function exportPresentationAsHtml(data: PresentationLike) {
  const html = await buildPresentationHtml(data);
  const fileName = safeHtmlFileName(data.title);
  const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return fileName;
}
