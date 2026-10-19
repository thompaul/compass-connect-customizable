import "src/_test_utilities/consoleMock";
import "src/_test_utilities/envServiceMock";

import React from "react";
import { render, screen } from "src/_test_utilities/test-utils";
import { routerPaths } from "src/app/routerPaths";
import * as envService from "src/envService";
import Footer, { DATA_TEST_ID } from "./Footer";

describe("Footer", () => {
  describe("a deployment that has declared nothing", () => {
    test("should credit nobody but the product", () => {
      // GIVEN a deployment with no partner logos, no contact address and no attribution
      // WHEN the Footer is rendered
      render(<Footer />);

      // THEN the footer is in the document
      const footerContainer = screen.getByTestId(DATA_TEST_ID.FOOTER_CONTAINER);
      expect(footerContainer).toBeInTheDocument();
      // AND no partner or funder logo is shown, because none was declared
      expect(screen.queryByTestId(DATA_TEST_ID.FOOTER_PARTNER_LOGO(0))).not.toBeInTheDocument();
      // AND the contact link is absent rather than pointing at somebody else's inbox
      expect(screen.queryByTestId(DATA_TEST_ID.FOOTER_CONTACT_LINK)).not.toBeInTheDocument();
      // AND no sponsor is claimed on the deployment's behalf
      expect(screen.queryByTestId(DATA_TEST_ID.FOOTER_COLLABORATION)).not.toBeInTheDocument();
      // AND the legal links are still there
      expect(screen.getByTestId(DATA_TEST_ID.FOOTER_PRIVACY_LINK)).toBeInTheDocument();
      expect(screen.getByTestId(DATA_TEST_ID.FOOTER_TERMS_LINK)).toBeInTheDocument();
      // AND to match the snapshot
      expect(footerContainer).toMatchSnapshot();
    });

    test("should open privacy and terms in a new tab via href", () => {
      // GIVEN the Footer
      // WHEN it is rendered
      render(<Footer />);

      // THEN the legal links point at this deployment's own pages
      const privacyLink = screen.getByTestId(DATA_TEST_ID.FOOTER_PRIVACY_LINK);
      const termsLink = screen.getByTestId(DATA_TEST_ID.FOOTER_TERMS_LINK);

      expect(privacyLink).toHaveAttribute("href", `${window.location.origin}/#${routerPaths.PRIVACY_POLICY}`);
      expect(privacyLink).toHaveAttribute("target", "_blank");
      expect(privacyLink).toHaveAttribute("rel", "noopener noreferrer");

      expect(termsLink).toHaveAttribute("href", `${window.location.origin}/#${routerPaths.TERMS_OF_USE}`);
      expect(termsLink).toHaveAttribute("target", "_blank");
      expect(termsLink).toHaveAttribute("rel", "noopener noreferrer");
    });
  });

  describe("a deployment that has declared its own", () => {
    test("should show the logos, contact address and attribution it declared", () => {
      // GIVEN a deployment that has declared two funders, an address and an attribution line
      jest
        .spyOn(envService, "getPartnerLogos")
        .mockReturnValue([{ src: "/a-funder.svg", alt: "A Funder" }, { src: "/another-funder.svg" }]);
      jest.spyOn(envService, "getContactEmail").mockReturnValue("hello@example.org");
      jest.spyOn(envService, "getFooterAttribution").mockReturnValue("Offered by the Example Ministry.");

      // WHEN the Footer is rendered
      render(<Footer />);

      // THEN both declared logos are shown
      expect(screen.getByTestId(DATA_TEST_ID.FOOTER_PARTNER_LOGO(0))).toBeInTheDocument();
      expect(screen.getByTestId(DATA_TEST_ID.FOOTER_PARTNER_LOGO(1))).toBeInTheDocument();
      // AND the contact link uses the declared address
      expect(screen.getByTestId(DATA_TEST_ID.FOOTER_CONTACT_LINK)).toHaveAttribute("href", "mailto:hello@example.org");
      // AND the declared attribution replaces the product's own
      expect(screen.getByTestId(DATA_TEST_ID.FOOTER_COLLABORATION)).toHaveTextContent(
        "Offered by the Example Ministry."
      );
    });
  });
});
