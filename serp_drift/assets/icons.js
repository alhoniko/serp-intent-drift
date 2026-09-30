/* One icon map for the whole app: 16 px grid, 1.5 px strokes. Replace a path here and every view follows. */
window.SerpIcons = (() => {
  'use strict';
  const c = (x, y, r) => `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
  const paths = {
    inbox: 'M2.5 9.5 4.1 4.3A1 1 0 0 1 5 3.5h6a1 1 0 0 1 .9.8l1.6 5.2v3a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1zM2.5 9.5h3l1 1.5h3l1-1.5h3',
    panels: 'M2.5 3.5h11v9h-11zM2.5 6.5h11M2.5 9.5h11',
    insights: 'M3 13V9M6.5 13V5M10 13V7.5M13.5 13V3.5',
    log: `M2.6 8a5.4 5.4 0 1 0 1.6-3.8M2.5 2.8v2.6h2.6M8 5.3V8l2 1.3`,
    settings: 'M2.5 4.5h6M11.5 4.5h2M10 3v3M2.5 11.5h2M7.5 11.5h6M6 10v3',
    projects: 'M2.5 4.5v7a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-5a1 1 0 0 0-1-1H8L6.5 3.5h-3a1 1 0 0 0-1 1z',
    agent: 'M6 2v3M10 2v3M4.5 5h7v2.5a3.5 3.5 0 0 1-7 0zM8 11v3',
    docs: 'M3 13V3.5A1.5 1.5 0 0 1 4.5 2H13v10H4.5A1.5 1.5 0 0 0 3 13.5 1.5 1.5 0 0 0 4.5 15H13v-3',
    external: 'M5.5 10.5l5-5M6.5 5.5h4v4',
    search: `${c(7, 7, 4.5)}M10.5 10.5 14 14`,
    updown: 'M5.5 6 8 3.5 10.5 6M5.5 10 8 12.5 10.5 10',
    down: 'M4 6l4 4 4-4',
    up: 'M4 10l4-4 4 4',
    right: 'M6 4l4 4-4 4',
    left: 'M10 4 6 8l4 4',
    source: `${c(5, 12, 1.6)}${c(11, 4, 1.6)}M5 10.4V3M11 5.6c0 2.6-6 1.8-6 4.8`,
    moon: 'M13 9.5A5.5 5.5 0 1 1 6.5 3a4.3 4.3 0 0 0 6.5 6.5z',
    sun: `${c(8, 8, 2.8)}M8 1.5v1.3M8 13.2v1.3M1.5 8h1.3M13.2 8h1.3M3.4 3.4l.9.9M11.7 11.7l.9.9M3.4 12.6l.9-.9M11.7 4.3l.9-.9`,
    system: 'M2.5 3.5h11v7h-11zM6 13.5h4M8 10.5v3',
    collect: 'M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3',
    x: 'M4.5 4.5l7 7M11.5 4.5l-7 7',
    check: 'M3.5 8.5l3 3 6-7',
    ok: `${c(8, 8, 6)}M5.5 8.2l1.8 1.8 3.3-3.6`,
    alert: 'M8 2.5 14 13H2zM8 6.5v3M8 11.5v.01',
    clock: `${c(8, 8, 6)}M8 4.8V8l2.2 1.4`,
    globe: `${c(8, 8, 6)}M2 8h12M8 2c-2 2.2-2 9.8 0 12M8 2c2 2.2 2 9.8 0 12`,
    quote: 'M3.5 7.5h3.2V11H3.5zM3.5 7.5c0-2.1.9-3.2 2.7-3.7M9.3 7.5h3.2V11H9.3zM9.3 7.5c0-2.1.9-3.2 2.7-3.7',
    activity: 'M1.5 8H4l2-4.5 3 9 2-4.5h3.5',
    target: `${c(8, 8, 6)}${c(8, 8, 3)}M8 8v.01`,
    page: 'M4 2h5.5L12.5 5v9h-8.5zM9.5 2v3h3M6 8.5h4.5M6 11h4.5',
    shield: 'M8 2l5 2v4c0 3-2.2 5-5 6-2.8-1-5-3-5-6V4zM5.8 8.2l1.6 1.6 3-3.2',
    compare: `${c(4.5, 12, 1.6)}${c(11.5, 4, 1.6)}M4.5 10.4V5.5A2 2 0 0 1 6.5 3.5H9M7.5 2 9 3.5 7.5 5M11.5 5.6v4.9a2 2 0 0 1-2 2H7M8.5 14 7 12.5 8.5 11`,
    more: `${c(3.5, 8, .6)}${c(8, 8, .6)}${c(12.5, 8, .6)}`,
    download: 'M8 2.5v8M4.5 7 8 10.5 11.5 7M3 13.5h10',
    plus: 'M8 3v10M3 8h10',
    copy: 'M5.5 5.5h8v8h-8zM10.5 5.5v-3h-8v8h3',
    play: 'M5 3.5v9l7.5-4.5z',
    eye: `M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8z${c(8, 8, 2)}`,
    info: `${c(8, 8, 6)}M8 7.5v3.5M8 5v.01`,
    features: 'M2.5 2.5h4.5v4.5h-4.5zM9 2.5h4.5v4.5H9zM2.5 9h4.5v4.5h-4.5zM9 9h4.5v4.5H9z',
    repeat: 'M2.5 7V6a2 2 0 0 1 2-2h8.5M11 2l2 2-2 2M13.5 9v1a2 2 0 0 1-2 2H3M5 14l-2-2 2-2',
    key: `${c(5, 10.5, 2.8)}M7 8.5 13 2.5M11 4.5l1.5 1.5M9.5 6l1.2 1.2`,
    bell: 'M4 11V7.2A4 4 0 0 1 12 7.2V11l1 1.5H3zM6.5 14h3',
    tags: `M2.5 2.5h5.3l6 6-5.3 5.3-6-6z${c(5.5, 5.5, .5)}`,
    timer: `${c(8, 9, 5)}M8 9V6.5M6.5 1.5h3`,
    workspace: 'M2.5 4.5v7a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-5a1 1 0 0 0-1-1H8L6.5 3.5h-3a1 1 0 0 0-1 1zM5.5 9.5h5',
    anchor: `${c(8, 3, 1.5)}M8 4.5V14M3 9a5 5 0 0 0 10 0M5.5 7h5`,
    scale: 'M8 2.5V14M4 14h8M3 4.5h10M3 4.5 1.5 9a1.8 1.8 0 0 0 3 0zM13 4.5 11.5 9a1.8 1.8 0 0 0 3 0z',
    checks: 'M2 4.5l1.3 1.3L6 3M2 10.5l1.3 1.3L6 9M8.5 4.5h5.5M8.5 10.5h5.5',
    keyboard: 'M1.5 4h13v8h-13zM4 6.5h.01M6.5 6.5h.01M9 6.5h.01M11.5 6.5h.01M4.5 9.5h7',
    sheet: 'M3 2h7l3 3v9H3zM10 2v3h3M5.5 8h5M5.5 10.5h5M8 8v5',
    message: 'M2.5 3.5h11v7.5h-6.5l-3 2.5v-2.5h-1.5z',
    menu: 'M2.5 4.5h11M2.5 8h11M2.5 11.5h11',
    arrowRight: 'M3 8h10M9 4l4 4-4 4',
    arrowUp: 'M8 13V3M4 7l4-4 4 4',
    arrowDown: 'M8 3v10M4 9l4 4 4-4',
    rejected: `${c(7, 7, 4.5)}M10.5 10.5 14 14M5.5 5.5l3 3M8.5 5.5l-3 3`,
    filter: 'M2 3.5h12L9.5 9v4l-3 1.5V9z',
    calc: 'M3.5 1.5h9v13h-9zM5.5 4h5v2.5h-5zM5.5 9h.01M8 9h.01M10.5 9h.01M5.5 11.5h.01M8 11.5h.01M10.5 11.5h.01',
    flask: 'M6 2h4M6.5 2v4L2.5 13a1 1 0 0 0 .9 1.5h9.2a1 1 0 0 0 .9-1.5L9.5 6V2M4.5 10.5h7',
    trash: 'M2.5 4h11M6 4V2.5h4V4M4 4l.7 10h6.6L12 4',
    pause: 'M5.5 3.5v9M10.5 3.5v9',
    open: 'M9.5 2.5h4v4M13.5 2.5l-6 6M11.5 9.5v4h-9v-9h4',
  };
  function get(name, cls = '') {
    const d = paths[name] || paths.info;
    return `<svg class="i${cls ? ` ${cls}` : ''}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`;
  }
  // The product mark: a rounded square cut along a fault line, the lower half drifted right. Same geometry as favicon.svg.
  function mark(cls = '') {
    return `<svg class="mark${cls ? ` ${cls}` : ''}" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M0 3.5A2.5 2.5 0 0 1 2.5 1h8A2.5 2.5 0 0 1 13 3.5v4H0zM3 8.5h13v4a2.5 2.5 0 0 1-2.5 2.5h-8A2.5 2.5 0 0 1 3 12.5z"/></svg>`;
  }
  return { get, mark, names: Object.keys(paths) };
})();
