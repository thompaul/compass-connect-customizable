import "src/_test_utilities/consoleMock";

import * as documents from "src/content/deploymentDocuments";
import { hasFaqDocument, loadFaqDocument, parseSections } from "src/faq/faqDocumentLoader";

jest.mock("src/content/deploymentDocuments", () => ({
  hasDocument: jest.fn(() => false),
  loadDocument: jest.fn(() => Promise.resolve(null)),
}));

const A_FAQ = `---
title: "Questions about Northway"
---

## 1. Getting started

### What is it?

A careers assistant.

### Does it cost anything?

No.

## 10. If something goes wrong

1. Reload the page.
2. Check that you are online.
`;

describe("faqDocumentLoader", () => {
  beforeEach(() => jest.clearAllMocks());

  test("a deployment that published no FAQ has none, so nothing links to one", () => {
    // GIVEN a deployment that supplied no FAQ
    (documents.hasDocument as jest.Mock).mockReturnValue(false);

    // THEN there is no FAQ, which is what the router and the navigation ask
    expect(hasFaqDocument()).toBe(false);
  });

  test("a deployment that published one has one", () => {
    // GIVEN a deployment that supplied a FAQ
    (documents.hasDocument as jest.Mock).mockImplementation((kind: string) => kind === "faq");

    // THEN it is reported as present
    expect(hasFaqDocument()).toBe(true);
    expect(documents.hasDocument).toHaveBeenCalledWith("faq");
  });

  test("loading when there is none answers with nothing rather than with an empty document", async () => {
    // GIVEN a deployment with no FAQ
    (documents.loadDocument as jest.Mock).mockResolvedValue(null);

    // WHEN it is loaded
    // THEN the caller can tell "none" apart from "an empty one"
    await expect(loadFaqDocument("en-GB")).resolves.toBeNull();
  });

  test("the deployment's own document is parsed into its sections", async () => {
    // GIVEN a deployment that published a FAQ
    (documents.loadDocument as jest.Mock).mockResolvedValue(A_FAQ);

    // WHEN it is loaded for a reader with British English selected
    const loaded = await loadFaqDocument("en-GB");

    // THEN the document is asked for in that language
    expect(documents.loadDocument).toHaveBeenCalledWith("faq", "en-GB");
    // AND its own title is used
    expect(loaded?.title).toBe("Questions about Northway");
    // AND its sections keep the numbers it gave them, so the checklist is recognised by number
    expect(loaded?.sections.map((section) => section.number)).toEqual([1, 10]);
    expect(loaded?.sections[0].items).toHaveLength(2);
    expect(loaded?.sections[1].kind).toBe("checklist");
  });

  test("parsing is unchanged for documents that have no questions in a section", () => {
    // GIVEN a section with prose and no questions
    const sections = parseSections("## 2. About us\n\nWe are a team.");

    // THEN it is kept as a static section rather than dropped
    expect(sections).toHaveLength(1);
    expect(sections[0].isStatic).toBe(true);
    expect(sections[0].staticMarkdown).toBe("We are a team.");
  });
});
