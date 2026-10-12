import "src/_test_utilities/consoleMock";

import * as envService from "src/envService";
import {
  clearDocumentCache,
  documentUrl,
  hasDocument,
  loadDocument,
  selectDocument,
} from "src/content/deploymentDocuments";

jest.mock("src/envService", () => ({
  getContentDocuments: jest.fn(() => []),
}));

const givenPublishedDocuments = (files: string[]) => {
  (envService.getContentDocuments as jest.Mock).mockReturnValue(files);
};

const givenTheNetworkServes = (bodyByUrl: Record<string, string>) => {
  const fetchMock = jest.fn((url: string) => {
    const body = bodyByUrl[url];
    if (body === undefined) {
      return Promise.resolve({ ok: false, status: 404, text: () => Promise.resolve("") });
    }
    return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(body) });
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
};

describe("deploymentDocuments", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    clearDocumentCache();
  });

  describe("what a deployment published", () => {
    test("a deployment that published nothing has nothing", () => {
      // GIVEN a deployment that supplied no documents
      givenPublishedDocuments([]);

      // THEN nothing of any kind is available
      expect(hasDocument("faq")).toBe(false);
      expect(hasDocument("privacy-policy")).toBe(false);
      expect(selectDocument("faq")).toBeUndefined();
    });

    test("a file nobody will ever ask for is ignored rather than guessed at", () => {
      // GIVEN a manifest carrying a name that does not follow the convention
      givenPublishedDocuments(["privacy_policy.md", "notes.md", "faq.md"]);

      // THEN only the well-named one counts
      expect(hasDocument("privacy-policy")).toBe(false);
      expect(hasDocument("faq")).toBe(true);
    });

    test("the URL is the deployment's own content directory", () => {
      // GIVEN a document file name
      // THEN it resolves under content/ in this deployment's bucket
      expect(documentUrl("faq.en-GB.md")).toBe(`${process.env.PUBLIC_URL}/content/faq.en-GB.md`);
    });
  });

  describe("choosing between languages", () => {
    test("an exact locale wins", () => {
      // GIVEN documents in two locales and one for all of them
      givenPublishedDocuments(["faq.md", "faq.en-GB.md", "faq.sw-KE.md"]);

      // WHEN a reader has Swahili selected
      // THEN they get the Swahili one
      expect(selectDocument("faq", "sw-KE")?.file).toBe("faq.sw-KE.md");
    });

    test("the same language in another region is preferred to no language at all", () => {
      // GIVEN a document for British English and one for every language
      givenPublishedDocuments(["faq.md", "faq.en-GB.md"]);

      // WHEN a reader has American English selected
      // THEN they get the English one rather than the unlabelled one
      expect(selectDocument("faq", "en-US")?.file).toBe("faq.en-GB.md");
    });

    test("a document written for every language serves a reader with no translation", () => {
      // GIVEN an unlocalised document and an English one
      givenPublishedDocuments(["terms-of-use.md", "terms-of-use.en-GB.md"]);

      // WHEN a reader has Spanish selected
      // THEN they get the one written for every language
      expect(selectDocument("terms-of-use", "es-ES")?.file).toBe("terms-of-use.md");
    });

    test("falling back to another language says so, because only publishing fixes it", () => {
      // GIVEN only an English document
      givenPublishedDocuments(["terms-of-use.en-GB.md"]);

      // WHEN a reader has Spanish selected
      const selected = selectDocument("terms-of-use", "es-ES");

      // THEN they are given the English one
      expect(selected?.file).toBe("terms-of-use.en-GB.md");
      // AND the fallback is reported, because the deployment is missing a translation
      expect(console.warn).toHaveBeenCalledWith(expect.stringContaining("es-ES"));
    });
  });

  describe("reading a document", () => {
    test("returns the text the deployment published", async () => {
      // GIVEN a published FAQ that the bucket serves
      givenPublishedDocuments(["faq.md"]);
      givenTheNetworkServes({ [documentUrl("faq.md")]: "# Hello" });

      // WHEN it is read
      // THEN the text comes back
      await expect(loadDocument("faq")).resolves.toBe("# Hello");
    });

    test("is read once however many times it is asked for", async () => {
      // GIVEN a published FAQ
      givenPublishedDocuments(["faq.md"]);
      const fetchMock = givenTheNetworkServes({ [documentUrl("faq.md")]: "# Hello" });

      // WHEN it is asked for three times
      await Promise.all([loadDocument("faq"), loadDocument("faq"), loadDocument("faq")]);

      // THEN the bucket was asked once
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    test("a read that fails is reported and answered with nothing, not with an exception", async () => {
      // GIVEN a document the manifest promises and the bucket does not have
      givenPublishedDocuments(["privacy-policy.md"]);
      givenTheNetworkServes({});

      // WHEN it is read
      // THEN the caller is told there is nothing, so it can show what it shows when there is none
      await expect(loadDocument("privacy-policy")).resolves.toBeNull();
      expect(console.error).toHaveBeenCalled();
    });

    test("a read that failed is tried again rather than remembered as absent", async () => {
      // GIVEN a document the bucket is not serving yet
      givenPublishedDocuments(["privacy-policy.md"]);
      givenTheNetworkServes({});
      await loadDocument("privacy-policy");

      // WHEN the bucket starts serving it
      givenTheNetworkServes({ [documentUrl("privacy-policy.md")]: "# Policy" });

      // THEN the next read gets it, rather than the session being stuck with the failure
      await expect(loadDocument("privacy-policy")).resolves.toBe("# Policy");
    });

    test("a kind the deployment never published is not requested at all", async () => {
      // GIVEN a deployment with only a FAQ
      givenPublishedDocuments(["faq.md"]);
      const fetchMock = givenTheNetworkServes({});

      // WHEN the privacy policy is read
      // THEN nothing is requested and the caller is told there is none
      await expect(loadDocument("privacy-policy")).resolves.toBeNull();
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });
});
