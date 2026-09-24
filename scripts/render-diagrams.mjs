import { readFile, writeFile, mkdir, rename, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import puppeteer from 'puppeteer';
import { renderMermaid } from '@mermaid-js/mermaid-cli';

const root = fileURLToPath(new URL('../', import.meta.url));
const docs = path.join(root, 'docs/week-02');
const destination = path.join(docs, 'diagrams');

// Markdown is the source of truth. The order follows the diagrams in each document.
const documents = [
  { file: '02-system-architecture.md', diagrams: [
    ['architecture-current', 'Текущая архитектура YaGo'],
    ['architecture-target', 'Целевая архитектура YaGo'],
    ['rental-sequence', 'Взаимодействие компонентов при начале аренды']
  ] },
  { file: '04-scooter-specification.md', diagrams: [
    ['vehicle-states', 'Состояния самоката и велосипеда'],
    ['rental-states', 'Жизненный цикл аренды']
  ] },
  { file: '05-er-model.md', diagrams: [
    ['er-model', 'ER-модель YaGo: основные сущности и связи']
  ] }
];

async function main() {
  const definitions = [];
  for (const { file, diagrams } of documents) {
    const markdown = await readFile(path.join(docs, file), 'utf8');
    const blocks = [...markdown.matchAll(/^```mermaid\s*\r?\n([\s\S]*?)^```\s*$/gm)];
    if (blocks.length !== diagrams.length) {
      throw new Error(`${file}: найдено ${blocks.length} Mermaid-блоков, ожидалось ${diagrams.length}. Обновите список в scripts/render-diagrams.mjs.`);
    }
    diagrams.forEach(([id, title], index) => {
      definitions.push({ id, title, file, source: `${blocks[index][1].trim()}\n` });
    });
  }

  const mermaidConfig = JSON.parse(await readFile(new URL('./mermaid.config.json', import.meta.url), 'utf8'));
  const launchOptions = { headless: true };
  // Optional local configuration, e.g. executablePath for an existing Chrome.
  if (process.env.MERMAID_PUPPETEER_CONFIG) {
    Object.assign(launchOptions, JSON.parse(await readFile(process.env.MERMAID_PUPPETEER_CONFIG, 'utf8')));
  }

  const browser = await puppeteer.launch(launchOptions);
  const outputs = [];
  try {
    for (const { id, title, file, source } of definitions) {
      const options = {
        viewport: { width: 2200, height: 1600, deviceScaleFactor: 2 },
        backgroundColor: '#ffffff',
        mermaidConfig: {
          ...mermaidConfig,
          deterministicIDSeed: id,
          // Keep the initial maintenance state above the many recovery cycles.
          ...(id === 'vehicle-states' ? {
            elk: {
              ...mermaidConfig.elk,
              cycleBreakingStrategy: 'DEPTH_FIRST',
              considerModelOrder: 'NODES_AND_EDGES'
            }
          } : {})
        },
        svgId: id
      };
      for (const format of ['svg', 'png']) {
        const { data } = await renderMermaid(browser, source, format, options);
        if (!data.length) throw new Error(`${id}.${format}: пустой результат`);
        outputs.push({ filename: `${id}.${format}`, data });
      }
      outputs.push({ filename: `${id}.mmd`, data: `%% Generated from ${file}; edit the Mermaid block there.\n${source}` });
      console.log(`Готово: ${title} (${id}.svg, ${id}.png)`);
    }
  } finally {
    await browser.close();
  }

  // Preserve the previous images if any diagram fails to render.
  await mkdir(destination, { recursive: true });
  for (const { filename, data } of outputs) {
    const target = path.join(destination, filename);
    const temporary = `${target}.${process.pid}.tmp`;
    try {
      await writeFile(temporary, data);
      await rename(temporary, target);
    } finally {
      await rm(temporary, { force: true });
    }
  }
  console.log(`Сохранено ${definitions.length} схем в docs/week-02/diagrams/. Галерея: index.html`);
}

main().catch(error => {
  console.error(`Не удалось построить схемы: ${error.message}`);
  process.exitCode = 1;
});
