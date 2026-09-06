const image = (top: string, bottom: string, accent: string, label: string) => {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 560"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="${top}"/><stop offset="1" stop-color="${bottom}"/></linearGradient><radialGradient id="r"><stop stop-color="${accent}" stop-opacity=".92"/><stop offset="1" stop-color="${accent}" stop-opacity="0"/></radialGradient></defs><rect width="800" height="560" fill="url(#g)"/><circle cx="590" cy="150" r="180" fill="url(#r)"/><path d="M0 410 145 270 265 375 390 220 555 390 675 290 800 430V560H0Z" fill="#07121b" opacity=".72"/><path d="M0 470 160 350 278 438 430 310 600 452 800 350V560H0Z" fill="#0e1c27" opacity=".7"/><text x="34" y="520" fill="#f2f7fa" opacity=".86" font-family="Segoe UI, sans-serif" font-size="24">${label}</text></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
};

export const mockImages = {
  lake: image("#0e5a92", "#102335", "#f7b65a", "MOCK / mountain lake"),
  portrait: image("#4d2e38", "#111925", "#e4a06f", "MOCK / studio portrait"),
  castle: image("#284e76", "#15142e", "#ffb66b", "MOCK / fantasy castle"),
  city: image("#4a1a53", "#0a1628", "#28b6cf", "MOCK / night city"),
  forest: image("#1d5a4b", "#0c1b23", "#e9c36b", "MOCK / forest cabin"),
  moon: image("#1b2f62", "#080e1c", "#c9d9ff", "MOCK / lunar landscape"),
  temple: image("#49637c", "#182034", "#efafbd", "MOCK / spring temple"),
  dog: image("#a66538", "#30211d", "#ffd487", "MOCK / golden retriever"),
};
