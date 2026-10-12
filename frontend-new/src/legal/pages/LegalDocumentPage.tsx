import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Box, Container, Typography, useTheme } from "@mui/material";
import { useTranslation } from "react-i18next";
import MarkdownReader from "src/knowledgeHub/components/MarkdownReader/MarkdownReader";
import { getProductName } from "src/envService";
import { getNotConfiguredLegalDocument, hasLegalDocument, loadLegalDocument } from "src/legal/legalDocumentLoader";
import type { LegalDocument, LegalDocumentVariant } from "src/legal/legalDocumentLoader";
import { routerPaths } from "src/app/routerPaths";
import { resolveDarkLogoUrl } from "src/branding/brandAssets";

const uniqueId = "b2c9e1a4-6f3d-4b8e-9c2a-1d5e7f0a4b6c";

export const DATA_TEST_ID = {
  LEGAL_PAGE_CONTAINER: `legal-page-container-${uniqueId}`,
  LEGAL_PAGE_LOGO: `legal-page-logo-${uniqueId}`,
  LEGAL_PAGE_TITLE: `legal-page-title-${uniqueId}`,
  LEGAL_PAGE_BODY: `legal-page-body-${uniqueId}`,
};

export interface LegalDocumentPageProps {
  variant: LegalDocumentVariant;
}

const applyAppNamePlaceholders = (text: string, appName: string): string => text.replaceAll("{{appName}}", appName);

const LegalDocumentPage: React.FC<LegalDocumentPageProps> = ({ variant }) => {
  const theme = useTheme();
  const { i18n } = useTranslation();
  const appName = getProductName();
  const locale = i18n.language;

  // A deployment that published nothing renders the placeholder on the first paint: whether
  // there is a document of its own is known from the configuration, without asking the
  // network, so there is no reason to show a reader a spinner on the way to an apology.
  const [legalDocument, setLegalDocument] = useState<LegalDocument>(() =>
    hasLegalDocument(variant) ? { title: "", markdown: "" } : getNotConfiguredLegalDocument(variant)
  );

  useEffect(() => {
    if (!hasLegalDocument(variant)) {
      setLegalDocument(getNotConfiguredLegalDocument(variant));
      return;
    }
    let cancelled = false;
    loadLegalDocument(variant, locale).then((loaded) => {
      if (!cancelled) setLegalDocument(loaded);
    });
    return () => {
      cancelled = true;
    };
  }, [variant, locale]);

  const { title, markdown } = legalDocument;
  const markdownWithAppName = useMemo(() => applyAppNamePlaceholders(markdown, appName), [markdown, appName]);

  const logoSrc = resolveDarkLogoUrl();

  return (
    <Box
      component="main"
      data-testid={DATA_TEST_ID.LEGAL_PAGE_CONTAINER}
      sx={{
        minHeight: "100vh",
        backgroundColor: theme.palette.pageBackground.main,
        py: theme.spacing(theme.tabiyaSpacing.lg),
        px: "var(--layout-gutter-x)",
      }}
    >
      <Container
        maxWidth="md"
        sx={{
          display: "flex",
          flexDirection: "column",
          gap: theme.spacing(theme.tabiyaSpacing.md),
        }}
      >
        <Link to={routerPaths.ROOT} aria-label="Go back">
          <Box
            component="img"
            src={logoSrc}
            alt={appName}
            data-testid={DATA_TEST_ID.LEGAL_PAGE_LOGO}
            sx={{ maxWidth: "120px", width: "auto", height: "auto", objectFit: "contain", alignSelf: "flex-start" }}
          />
        </Link>

        <Typography variant="h2" textAlign="center" data-testid={DATA_TEST_ID.LEGAL_PAGE_TITLE}>
          {title}
        </Typography>

        <Box data-testid={DATA_TEST_ID.LEGAL_PAGE_BODY}>
          <MarkdownReader content={markdownWithAppName} headingEmphasis />
        </Box>
      </Container>
    </Box>
  );
};

export default LegalDocumentPage;
