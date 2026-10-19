import "src/_test_utilities/consoleMock";

// The markdown placeholders are `raw-loader` imports, and under this runner they resolve to
// their own file names rather than their contents - CRA's asset transform claims `.md` before
// the project's raw-loader transform gets it. So these tests check which document is chosen and
// that nothing is fetched to choose it; what the placeholders actually say is checked where the
// files can be read, in `iac/test_no_partner_defaults.py`.

import * as documents from "src/content/deploymentDocuments";
import { getNotConfiguredLegalDocument, hasLegalDocument, loadLegalDocument } from "src/legal/legalDocumentLoader";

jest.mock("src/content/deploymentDocuments", () => ({
  hasDocument: jest.fn(() => false),
  loadDocument: jest.fn(() => Promise.resolve(null)),
}));

const givenTheDeploymentPublished = (kinds: string[], text?: string) => {
  (documents.hasDocument as jest.Mock).mockImplementation((kind: string) => kinds.includes(kind));
  (documents.loadDocument as jest.Mock).mockImplementation((kind: string) =>
    Promise.resolve(kinds.includes(kind) ? text ?? "" : null)
  );
};

describe("legalDocumentLoader", () => {
  beforeEach(() => jest.clearAllMocks());

  test("a deployment that published nothing is told so, rather than shown somebody else's", async () => {
    // GIVEN a deployment with no legal documents of its own
    givenTheDeploymentPublished([]);

    // THEN nothing is claimed to exist
    expect(hasLegalDocument("privacy")).toBe(false);

    // AND the page shown is the placeholder, which says so in as many words
    const loaded = await loadLegalDocument("privacy");
    expect(loaded).toEqual(getNotConfiguredLegalDocument("privacy"));
  });

  test("the placeholder is available without asking the network at all", () => {
    // GIVEN nothing - this is the page shown when a read has already failed
    // WHEN the placeholder is asked for
    const placeholder = getNotConfiguredLegalDocument("terms");

    // THEN it is there, synchronously, and nothing was fetched to produce it
    expect(placeholder.markdown).not.toHaveLength(0);
    expect(documents.loadDocument).not.toHaveBeenCalled();
    // AND it is the terms placeholder rather than the privacy one
    expect(placeholder).not.toEqual(getNotConfiguredLegalDocument("privacy"));
  });

  test("a deployment's own document is shown with the title it gave it", async () => {
    // GIVEN a deployment that published a privacy policy with frontmatter
    givenTheDeploymentPublished(
      ["privacy-policy"],
      '---\ntitle: "Aviso de privacidad"\n---\n\nSomos responsables de sus datos.\n'
    );

    // WHEN it is loaded
    const loaded = await loadLegalDocument("privacy", "es-ES");

    // THEN the deployment's own title and body are used
    expect(loaded.title).toBe("Aviso de privacidad");
    expect(loaded.markdown).toBe("Somos responsables de sus datos.\n");
  });

  test("a read that failed falls back to the placeholder rather than to an empty page", async () => {
    // GIVEN a deployment that published a document the read could not retrieve
    (documents.hasDocument as jest.Mock).mockReturnValue(true);
    (documents.loadDocument as jest.Mock).mockResolvedValue(null);

    // WHEN it is loaded
    const loaded = await loadLegalDocument("terms");

    // THEN the reader gets the placeholder, which is at least true of what they can see,
    // instead of a blank page with no explanation
    expect(loaded).toEqual(getNotConfiguredLegalDocument("terms"));
  });
});
