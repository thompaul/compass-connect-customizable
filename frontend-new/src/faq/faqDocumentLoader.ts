import { getProductName } from "src/envService";
import { parseYamlFrontmatter } from "src/utils/parseYamlFrontmatter";

import faqEnGbMd from "!!raw-loader!./documents/faq.en-GB.md";
import faqEnUsMd from "!!raw-loader!./documents/faq.en-US.md";
import faqEsEsMd from "!!raw-loader!./documents/faq.es-ES.md";
import faqEsArMd from "!!raw-loader!./documents/faq.es-AR.md";
import faqNyZmMd from "!!raw-loader!./documents/faq.ny-ZM.md";
import faqSwKeMd from "!!raw-loader!./documents/faq.sw-KE.md";
import faqPtMzMd from "!!raw-loader!./documents/faq.pt-MZ.md";

/** Section number for the troubleshooting checklist in all FAQ locale documents. */
export const CHECKLIST_SECTION_NUMBER = 10;

/**
 * The FAQ documents belonging to the deployments that wrote them, keyed by the product name
 * each one deploys under and then by locale.
 *
 * The outer key is the whole point of this change. These documents were keyed by locale
 * alone, so **every** deployment served them: forty-odd paragraphs per language opening
 * "Njila is a free AI career guidance platform built for the Zambian youth, supported by a
 * collaboration between the Ministry of Technical and Vocational Skills Development (MoTS)
 * of Zambia and the World Bank Group." No configuration changed it, because none was
 * consulted. It was not a default a deployment could override - it was the only answer.
 *
 * A deployment whose name is not here has no FAQ, and `app/index.tsx` registers no route for
 * one. Loading these at runtime from the deployment's own assets, the way its logo now
 * arrives, is the change that retires this map.
 */
const FAQ_BY_PRODUCT: Record<string, Record<string, string>> = {
  njila: {
    "en-GB": faqEnGbMd,
    "en-US": faqEnUsMd,
    "es-ES": faqEsEsMd,
    "es-AR": faqEsArMd,
    "ny-ZM": faqNyZmMd,
    "sw-KE": faqSwKeMd,
    "pt-MZ": faqPtMzMd,
  },
};

const faqForThisDeployment = (): Record<string, string> | undefined =>
  FAQ_BY_PRODUCT[getProductName().toLowerCase()];

/** Whether this deployment has a FAQ at all. Nothing links to one that does not exist. */
export const hasFaqDocument = (): boolean => faqForThisDeployment() !== undefined;

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

export const getFaqDocument = (locale?: string): FaqDocument => {
  const documents = faqForThisDeployment();
  if (!documents) {
    // Reached only if something links to the FAQ without checking hasFaqDocument first.
    return { title: "", sections: [] };
  }
  const markdown = (locale && documents[locale]) ?? Object.values(documents)[0];
  const { data, content } = parseYamlFrontmatter(markdown);
  return {
    title: data.title,
    sections: parseSections(content.trim()),
  };
};
