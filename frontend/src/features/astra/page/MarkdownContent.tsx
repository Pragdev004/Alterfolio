import { Fragment, type ReactNode } from "react";

type MarkdownContentProps = {
  content: string;
};

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^\)]+\))/g;
  const parts = text.split(pattern).filter(Boolean);

  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`;

    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }

    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }

    if (part.startsWith("[") && part.includes("](") && part.endsWith(")")) {
      const splitIndex = part.indexOf("](");
      const label = part.slice(1, splitIndex);
      const href = part.slice(splitIndex + 2, -1);

      return (
        <a key={key} href={href} target="_blank" rel="noreferrer" className="astra-link">
          {label}
        </a>
      );
    }

    return <Fragment key={key}>{part}</Fragment>;
  });
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  const lines = content.split(/\r?\n/);
  const nodes: ReactNode[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]?.trim() ?? "";

    if (!line) {
      continue;
    }

    if (line.startsWith("### ")) {
      nodes.push(
        <h4 key={`h4-${index}`} className="astra-markdown-h4">
          {renderInlineMarkdown(line.slice(4), `h4-${index}`)}
        </h4>
      );
      continue;
    }

    if (line.startsWith("## ")) {
      nodes.push(
        <h3 key={`h3-${index}`} className="astra-markdown-h3">
          {renderInlineMarkdown(line.slice(3), `h3-${index}`)}
        </h3>
      );
      continue;
    }

    if (line.startsWith("# ")) {
      nodes.push(
        <h2 key={`h2-${index}`} className="astra-markdown-h2">
          {renderInlineMarkdown(line.slice(2), `h2-${index}`)}
        </h2>
      );
      continue;
    }

    if (line.startsWith("- ")) {
      const items: string[] = [];
      let cursor = index;

      while (cursor < lines.length) {
        const current = lines[cursor]?.trim() ?? "";
        if (!current.startsWith("- ")) {
          break;
        }

        items.push(current.slice(2));
        cursor += 1;
      }

      nodes.push(
        <ul key={`ul-${index}`} className="astra-markdown-list">
          {items.map((item, itemIndex) => (
            <li key={`li-${index}-${itemIndex}`}>
              {renderInlineMarkdown(item, `li-${index}-${itemIndex}`)}
            </li>
          ))}
        </ul>
      );

      index = cursor - 1;
      continue;
    }

    nodes.push(
      <p key={`p-${index}`} className="astra-markdown-paragraph">
        {renderInlineMarkdown(line, `p-${index}`)}
      </p>
    );
  }

  return <>{nodes}</>;
}
