import { parseYamlFrontmatter } from "src/utils/parseYamlFrontmatter";
import { hasDocument, loadDocument } from "src/content/deploymentDocuments";

/** Section number for the troubleshooting checklist in all FAQ locale documents. */
export const CHECKLIST_SECTION_NUMBER = 10;

/**
 * Whether this deployment has a FAQ at all, from the list of documents it published.
 *
 * The FAQ used to be seven markdown files compiled into the bundle and keyed by locale
 * alone - no product, no configuration, nothing to override. So every deployment served
 * forty-odd paragraphs opening "Njila is a free AI career guidance platform built for the
 * Zambian youth, supported by a collaboration between the Ministry of Technical and
 * Vocational Skills Development (MoTS) of Zambia and the World Bank Group", in whichever of
 * seven languages the reader had chosen. It was not a default a deployment could override;
 * it was the only answer.
 *
 * A deployment now has the FAQ it wrote, and a deployment that wrote none has none: nothing
 * links to it and `app/index.tsx` registers no route for it.
 */
export const hasFaqDocument = (): boolean => hasDocument("faq");

export interface FaqQuestion {
  id: string;
  question: string;
  answerMarkdown: string;
}

export type FaqSectionKind = "qa" | "static" | "checklist";

export interface FaqSection {
  id: string;
  number: number;
  title: string;
  items: FaqQuestion[];
  staticMarkdown?: string;
  isStatic: boolean;
  kind: FaqSectionKind;
}

export interface FaqDocument {
  title: string;
  sections: FaqSection[];
}

const slugify = (raw: string): string =>
  raw
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 80) || "section";

export const parseSections = (markdown: string): FaqSection[] => {
  const sectionBlocks = markdown
    .split(/\n(?=## )/)
    .map((s) => s.trim())
    .filter((s) => s.startsWith("## "));

  return sectionBlocks.map((block, index) => {
    const headingEnd = block.indexOf("\n");
    const headingLine = headingEnd === -1 ? block : block.slice(0, headingEnd);
    const body = headingEnd === -1 ? "" : block.slice(headingEnd + 1).trim();

    const headingText = headingLine.replace(/^##\s+/, "").trim();
    const numberedMatch = headingText.match(/^(\d+)\.\s*(.+)$/);
    const number = numberedMatch ? parseInt(numberedMatch[1], 10) : index + 1;
    const title = numberedMatch ? numberedMatch[2].trim() : headingText;

    const itemBlocks = body
      .split(/\n(?=### )/)
      .map((s) => s.trim())
      .filter((s) => s.startsWith("### "));

    const id = slugify(title);

    if (itemBlocks.length === 0) {
      const kind: FaqSectionKind = number === CHECKLIST_SECTION_NUMBER ? "checklist" : "static";
      return {
        id,
        number,
        title,
        items: [],
        staticMarkdown: body,
        isStatic: true,
        kind,
      };
    }

    const items: FaqQuestion[] = itemBlocks.map((itemBlock) => {
      const itemHeadingEnd = itemBlock.indexOf("\n");
      const itemHeading = itemHeadingEnd === -1 ? itemBlock : itemBlock.slice(0, itemHeadingEnd);
      const itemBody = itemHeadingEnd === -1 ? "" : itemBlock.slice(itemHeadingEnd + 1).trim();
      const question = itemHeading.replace(/^###\s+/, "").trim();
      return {
        id: `${id}--${slugify(question)}`,
        question,
        answerMarkdown: itemBody,
      };
    });

    return {
      id,
      number,
      title,
      items,
      isStatic: false,
      kind: "qa",
    };
  });
};

/**
 * This deployment's FAQ in the reader's language, or null when there is nothing to show.
 *
 * Null covers both "this deployment published no FAQ" and "the document could not be read".
 * The caller renders the same thing for each, because a reader can act on neither.
 */
export const loadFaqDocument = async (locale?: string): Promise<FaqDocument | null> => {
  const markdown = await loadDocument("faq", locale);
  if (markdown === null) return null;

  const { data, content } = parseYamlFrontmatter(markdown);
  return {
    title: data.title,
    sections: parseSections(content.trim()),
  };
};
