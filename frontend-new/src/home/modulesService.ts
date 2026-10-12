import { routerPaths } from "src/app/routerPaths";
import { getKnowledgeHubEnabled } from "src/envService";

export interface Module {
  id: string;
  labelKey: string;
  descriptionKey: string;
  route: string;
  disabled?: boolean;
  /**
   * The id of the next top-level module to suggest when this module completes.
   * Leave undefined if there is no automatic handoff.
   */
  nextModuleId?: string;
}

/**
 * The default set of modules that are always available on the Home page.
 */
const DEFAULT_MODULES: Module[] = [
  {
    id: "skills_discovery",
    labelKey: "home.modules.skillsDiscovery",
    descriptionKey: "home.modules.skillsDiscoveryDesc",
    route: routerPaths.SKILLS_INTERESTS,
    nextModuleId: "career_explorer",
  },
  {
    id: "career_explorer",
    labelKey: "home.modules.careerExplorer",
    descriptionKey: "home.modules.careerExplorerDesc",
    route: routerPaths.CAREER_EXPLORER,
  },
  {
    id: "job_readiness",
    labelKey: "home.modules.jobReadiness",
    descriptionKey: "home.modules.jobReadinessDesc",
    route: routerPaths.CAREER_READINESS,
    nextModuleId: "knowledge_hub",
  },
  {
    id: "knowledge_hub",
    labelKey: "home.modules.knowledgeHub",
    descriptionKey: "home.modules.knowledgeHubDesc",
    route: routerPaths.KNOWLEDGE_HUB,
  },
  {
    id: "job_matching",
    labelKey: "home.modules.jobMatching",
    descriptionKey: "home.modules.jobMatchingDesc",
    route: routerPaths.JOB_MATCHING,
  },
];

/**
 * The modules this deployment offers on its home page.
 *
 * The knowledge hub leaves the list when it is off, so a deployment that does not serve the
 * route does not advertise it either. A card leading to a page that is not registered is a
 * 404 the visitor reads as a broken product rather than as a module nobody turned on.
 *
 * `nextModuleId` is repaired in the same pass: career readiness hands off to the knowledge
 * hub, and a handoff to a module that is not there would strand whoever completed it.
 */
export const getEnabledModules = (): Module[] => {
  const enabled = getKnowledgeHubEnabled()
    ? DEFAULT_MODULES
    : DEFAULT_MODULES.filter((module) => module.id !== "knowledge_hub");

  const present = new Set(enabled.map((module) => module.id));
  return enabled.map((module) =>
    module.nextModuleId && !present.has(module.nextModuleId)
      ? { ...module, nextModuleId: undefined }
      : module
  );
};
