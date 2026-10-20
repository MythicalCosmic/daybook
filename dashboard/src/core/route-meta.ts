/** Typed `route.meta` for every route in the console. */
import type { CompanyFeature } from "@/core/features";
import type { PermRequirement } from "@/core/perms";

declare module "vue-router" {
  interface RouteMeta {
    /** Required permission (any of a list). */
    perm?: PermRequirement;
    /** Required `Company.features` switch. */
    feature?: CompanyFeature;
    /** i18n key for the breadcrumb and the document title. */
    title?: string;
    /** Owning module id; the router stamps it on every module route. */
    module?: string;
    /** Reachable without a session (login). */
    public?: boolean;
    /** Signed-in page outside any company (portfolio). */
    companyless?: boolean;
    /** "full": the page manages its own padding and scrolling (boards, maps, chat). */
    layout?: "default" | "full";
  }
}

export {};
