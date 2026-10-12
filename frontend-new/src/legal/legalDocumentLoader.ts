import { parseYamlFrontmatter } from "src/utils/parseYamlFrontmatter";
import { hasDocument, loadDocument, type DocumentKind } from "src/content/deploymentDocuments";

import privacyPolicyNotConfiguredMd from "!!raw-loader!./documents/privacy-policy-not-configured.md";
import termsOfUseNotConfiguredMd from "!!raw-loader!./documents/terms-of-use-not-configured.md";

export type LegalDocumentVariant = "privacy" | "terms";

export interface LegalDocument {
  title: string;
  markdown: string;
}

/** The file each page looks for in this deployment's own `content/` directory. */
const DOCUMENT_KIND: Record<LegalDocumentVariant, DocumentKind> = {
  privacy: "privacy-policy",
  terms: "terms-of-use",
};

/**
 * What a deployment shows when it has not published legal documents of its own.
 *
 * It says so, in as many words. The alternative — quietly showing some other organisation's
 * privacy policy — tells a user that a named third party is the data controller for data that
 * party never receives, which is worse than an empty page rather than better than one.
 *
 * Compiled in, unlike the documents themselves. This is the page shown when nothing was
 * published or when the read failed, so it is the one page that must not depend on a request
 * succeeding.
 */
const NOT_CONFIGURED: Record<LegalDocumentVariant, string> = {
  privacy: privacyPolicyNotConfiguredMd,
  terms: termsOfUseNotConfiguredMd,
};

const parse = (raw: string): LegalDocument => {
  const { data, content } = parseYamlFrontmatter(raw);
  return { title: data.title, markdown: content.trimStart() };
};

/**
 * Whether this deployment published this document.
 *
 * Synchronous, so a deployment that published nothing renders the placeholder on the first
 * paint instead of showing a reader a spinner on the way to an apology.
 */
export const hasLegalDocument = (variant: LegalDocumentVariant): boolean => hasDocument(DOCUMENT_KIND[variant]);

export const getNotConfiguredLegalDocument = (variant: LegalDocumentVariant): LegalDocument =>
  parse(NOT_CONFIGURED[variant]);

/**
 * This deployment's own privacy policy or terms of use, in the reader's language where there
 * is one, falling back to the placeholder when there is nothing to show.
 */
export const loadLegalDocument = async (variant: LegalDocumentVariant, locale?: string): Promise<LegalDocument> => {
  const markdown = await loadDocument(DOCUMENT_KIND[variant], locale);
  return parse(markdown ?? NOT_CONFIGURED[variant]);
};
