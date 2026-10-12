import React from "react";
import { resolveChatAvatarUrl } from "src/branding/brandAssets";

const BrandLogo: React.FC = () => (
  <img
    src={resolveChatAvatarUrl()}
    alt="brand logo"
    width={44}
    height={44}
    style={{ borderRadius: "50%", objectFit: "contain" }}
  />
);

export default BrandLogo;
