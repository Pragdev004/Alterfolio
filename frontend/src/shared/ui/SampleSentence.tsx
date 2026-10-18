import type { NumberOut } from "../api/types";

/** Shown where a verdict would sit when there are too few trips. The count text is the server's, never composed here. */
export function TooFew({ sampleText, headline = "Not enough closed trips to say anything yet." }: { sampleText: string; headline?: string }) {
  return (
    <div className="too-few">
      <strong>{headline}</strong>
      <span>{sampleText}</span>
    </div>
  );
}

export const reasonOf = (n: NumberOut): string | null => n.reason_text;
