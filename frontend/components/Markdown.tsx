// Renderizador de markdown mínimo e seguro para respostas da IA.
//
// Gera elementos React (nunca HTML cru / dangerouslySetInnerHTML): o texto
// vem de um modelo e é tratado como não confiável. Suporta o que o agente de
// marketing usa: títulos (#..###), listas (-, *, 1.), tabelas com pipes,
// **negrito**, *itálico*, `código` e links http(s).

import type { ReactNode } from "react";
import styles from "./Markdown.module.css";

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|\*[^*\s][^*]*\*)/g;

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${keyBase}-${i}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
    if (link) {
      return (
        <a key={key} href={link[2]} target="_blank" rel="noreferrer noopener">
          {link[1]}
        </a>
      );
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

function isTableRow(line: string) {
  return /^\s*\|.*\|\s*$/.test(line);
}

function cells(line: string): string[] {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

export default function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const key = `b${i}`;

    if (!line.trim()) {
      i++;
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      const content = inline(heading[2], key);
      blocks.push(
        level <= 2 ? (
          <h3 key={key} className={styles.h}>
            {content}
          </h3>
        ) : (
          <h4 key={key} className={styles.h4}>
            {content}
          </h4>
        ),
      );
      i++;
      continue;
    }

    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      blocks.push(<hr key={key} className={styles.hr} />);
      i++;
      continue;
    }

    if (isTableRow(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      const header = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(cells(lines[i]));
        i++;
      }
      blocks.push(
        <div key={key} className={styles.tableWrap}>
          <table>
            <thead>
              <tr>
                {header.map((h, j) => (
                  <th key={j}>{inline(h, `${key}h${j}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((c, ci) => (
                    <td key={ci}>{inline(c, `${key}r${ri}c${ci}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    const bullet = /^\s*[-*•]\s+/;
    const numbered = /^\s*\d+[.)]\s+/;
    if (bullet.test(line) || numbered.test(line)) {
      const ordered = numbered.test(line);
      const pattern = ordered ? numbered : bullet;
      const items: ReactNode[] = [];
      while (i < lines.length && pattern.test(lines[i])) {
        items.push(<li key={i}>{inline(lines[i].replace(pattern, ""), `${key}l${i}`)}</li>);
        i++;
      }
      blocks.push(
        ordered ? (
          <ol key={key} className={styles.list}>
            {items}
          </ol>
        ) : (
          <ul key={key} className={styles.list}>
            {items}
          </ul>
        ),
      );
      continue;
    }

    // Parágrafo: junta linhas até uma em branco ou outro bloco
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,4})\s/.test(lines[i]) &&
      !bullet.test(lines[i]) &&
      !numbered.test(lines[i]) &&
      !isTableRow(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key} className={styles.p}>
        {para.flatMap((p, j) => [
          ...(j ? [<br key={`br${j}`} />] : []),
          ...inline(p, `${key}p${j}`),
        ])}
      </p>,
    );
  }

  return <div className={styles.md}>{blocks}</div>;
}
