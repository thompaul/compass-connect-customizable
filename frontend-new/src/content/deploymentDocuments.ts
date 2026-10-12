import { getContentDocuments } from "src/envService";

/**
 * The documents a deployment writes for itself, fetched from its own bucket when asked for.
 *
 * Until now these were compiled in. The privacy policy, the terms of use and the FAQ were
 * `raw-loader` imports in Tabiya's repository, keyed by product name and locale, which meant
 * a partner could only publish their own by changing Tabiya's source and rebuilding — the
 * precise thing this phase exists to stop. Worse, the keying was by locale alone for the FAQ,
 * so one partner's forty paragraphs about one country's programme were served, in seven
 * languages, by every deployment that existed.
 *
 * They now travel the same road as a logo: the operator's `assets/content/` directory, into
 * the bundle, into the bucket. The difference from a logo is that nothing configures a URL
 * for them, so the deployment writes down which ones it has — see `getContentDocuments` —
 * and this module turns that list into a URL and the file at it into text.
 */
export type DocumentKind = "privacy-policy" | "terms-of-use" | "faq";

/** Where the documents sit in the bundle, matching `CONTENT_DIRECTORY_NAME` in the deployment. */
export const CONTENT_PATH = "content";

interface DeploymentDocument {
  kind: DocumentKind;
  /** The locale this one is written in, or undefined for a document that serves all of them. */
  locale?: string;
  file: string;
}

const DOCUMENT_NAME = /^(privacy-policy|terms-of-use|faq)(?:\.([A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*))?\.md$/;

const parseDocumentName = (file: string): DeploymentDocument | null => {
  const match = DOCUMENT_NAME.exec(file);
  if (!match) return null;
  return { kind: match[1] as DocumentKind, locale: match[2], file };
};

const documentsOfKind = (kind: DocumentKind): DeploymentDocument[] =>
  getContentDocuments()
    .map(parseDocumentName)
    .filter((entry): entry is DeploymentDocument => entry !== null && entry.kind === kind);

/**
 * Whether this deployment published a document of this kind at all.
 *
 * Synchronous, and deliberately so: the FAQ route and the FAQ menu entry are decided by this,
 * and they have to be decided before the first render rather than after a fetch resolves.
 */
export const hasDocument = (kind: DocumentKind): boolean => documentsOfKind(kind).length > 0;

/**
 * The best document of this kind for a reader in this language.
 *
 * Exact locale first, then any document in the same language, then one written for every
 * language, then whatever there is. The last step is a real fallback rather than a tidy one —
 * it can hand a Portuguese reader an English page — so it says so out loud, because the fix
 * is to publish the missing translation and nobody can fix what nothing reports.
 */
export const selectDocument = (kind: DocumentKind, locale?: string): DeploymentDocument | undefined => {
  const candidates = documentsOfKind(kind);
  if (candidates.length === 0) return undefined;

  const language = locale?.split("-")[0];
  const exact = candidates.find((entry) => entry.locale === locale);
  if (exact) return exact;

  const sameLanguage = language ? candidates.find((entry) => entry.locale?.split("-")[0] === language) : undefined;
  if (sameLanguage) return sameLanguage;

  const anyLanguage = candidates.find((entry) => entry.locale === undefined);
  if (anyLanguage) return anyLanguage;

  const fallback = candidates[0];
  console.warn(
    `No ${kind} document for '${locale}'; showing the one written for '${fallback.locale}' instead.`
  );
  return fallback;
};

export const documentUrl = (file: string): string => `${process.env.PUBLIC_URL}/${CONTENT_PATH}/${file}`;

/**
 * Read once and remembered.
 *
 * These files do not change while a page is open — a deployment changes them by deploying —
 * so re-reading one because a reader switched tabs or came back to a page would be a request
 * that could only ever return the same bytes.
 */
const inFlight = new Map<string, Promise<string>>();

export const clearDocumentCache = (): void => {
  inFlight.clear();
};

const read = (file: string): Promise<string> => {
  const pending = inFlight.get(file);
  if (pending) return pending;

  const request = fetch(documentUrl(file))
    .then((response) => {
      if (!response.ok) {
        throw new Error(`${documentUrl(file)} responded ${response.status}`);
      }
      return response.text();
    })
    .catch((error) => {
      // Forget the failure, so a document missed because the network was down is tried again
      // rather than being permanently absent for the rest of the session.
      inFlight.delete(file);
      throw error;
    });

  inFlight.set(file, request);
  return request;
};

/**
 * The text of this deployment's document, or null when it has not published one.
 *
 * Null is also what a failed read returns, after saying so: every caller already has
 * something to show when there is no document, and that is a better answer to a network
 * failure than an empty page with no explanation.
 */
export const loadDocument = async (kind: DocumentKind, locale?: string): Promise<string | null> => {
  const selected = selectDocument(kind, locale);
  if (!selected) return null;

  try {
    return await read(selected.file);
  } catch (error) {
    console.error(new Error(`Could not read the deployment's ${kind} document`, { cause: error }));
    return null;
  }
};
