import { getProductName } from "src/envService";
import { parseYamlFrontmatter } from "src/utils/parseYamlFrontmatter";

import privacyPolicyNotConfiguredMd from "!!raw-loader!./documents/privacy-policy-not-configured.md";
import termsOfUseNotConfiguredMd from "!!raw-loader!./documents/terms-of-use-not-configured.md";
import privacyPolicyNjilaMd from "!!raw-loader!./documents/privacy-policy.md";
import termsOfUseNjilaMd from "!!raw-loader!./documents/terms-of-use.md";
import privacyPolicyNjiraMd from "!!raw-loader!./documents/privacy-policy-njira.md";
import termsOfUseNjiraMd from "!!raw-loader!./documents/terms-of-use-njira.md";

export type LegalDocumentVariant = "privacy" | "terms";

export interface LegalDocument {
  title: string;
  markdown: string;
}

/**
 * What a deployment shows when it has not published legal documents of its own.
 *
 * It says so, in as many words. The alternative — quietly showing some other organisation's
 * privacy policy — tells a user that a named third party is the data controller for data that
 * party never receives, which is worse than an empty page rather than better than one.
 */
const NOT_CONFIGURED: Record<LegalDocumentVariant, string> = {
  privacy: privacyPolicyNotConfiguredMd,
  terms: termsOfUseNotConfiguredMd,
};

/**
 * Documents belonging to the deployments that predate configurable legal content, keyed by the
 * product name each one deploys under. Nothing resolves here unless its own name is configured,
 * and the default product name deliberately does not appear: a deployment that has not been
 * branded has not been given legal documents either.
 *
 * This is a compatibility shim, not the mechanism. Legal documents are compiled into the bundle
 * by the raw loader, so a deployment cannot supply its own without rebuilding the frontend —
 * which is why a new deployment gets the placeholder above. Loading these at runtime from the
 * deployment's own assets is the change that retires this map.
 */
const documentsByProductName: Record<string, Record<LegalDocumentVariant, string>> = {
  njila: { privacy: privacyPolicyNjilaMd, terms: termsOfUseNjilaMd },
  njira: { privacy: privacyPolicyNjiraMd, terms: termsOfUseNjiraMd },
};

export const getLegalDocument = (variant: LegalDocumentVariant): LegalDocument => {
  const key = getProductName().toLowerCase();
  const registry = documentsByProductName[key] ?? NOT_CONFIGURED;
  const { data, content } = parseYamlFrontmatter(registry[variant]);
  return {
    title: data.title,
    markdown: content.trimStart(),
  };
};
