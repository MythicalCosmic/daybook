/**
 * Recognition (Rag‘batlantirish, PLAN-LEARNING §7, §11, package R): the leaderboard (a podium for
 * the top three, everyone's points, levels, badges and streaks, any week or month, a branch
 * filter, export), thanks between colleagues with hide, the badge catalogue with who has each,
 * and Settings › Recognition with the points table. It also fills learning's person page (their
 * points and badges), learning's overview (this week's top learners) and Person 360's header
 * ("Say thanks"). Behind the "recognition" switch. Pages load on first use (lazy.ts).
 */
import { HeartHandshake, Trophy } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { READ } from "./lib";
import { lazy, routes } from "./routes";

export default defineModule({
  id: "recognition",
  group: "people",
  order: 60,
  icon: Trophy,
  title: "recognition.title",
  perm: READ,
  feature: "recognition",
  routes,
  nav: [
    { key: "leaderboard", title: "recognition.nav.leaderboard", to: "recognition", exact: true },
    { key: "kudos", title: "recognition.nav.kudos", to: "recognition/kudos" },
    { key: "badges", title: "recognition.nav.badges", to: "recognition/badges" },
  ],
  invalidates: ["recognition"],
  commands: (ctx) => [
    {
      id: "recognition.leaderboard",
      title: ctx.t("recognition.cmd.leaderboard"),
      icon: Trophy,
      keywords: ["reyting", "рейтинг", "leaderboard", "ball", "баллы", "points"],
      perm: READ,
      run: () => ctx.go("recognition"),
    },
    {
      id: "recognition.thanks",
      title: ctx.t("recognition.cmd.thanks"),
      icon: HeartHandshake,
      keywords: ["rahmat", "спасибо", "благодарность", "kudos", "thanks"],
      perm: READ,
      run: () => ctx.go("recognition/kudos"),
    },
  ],
  settings: [
    {
      id: "recognition",
      title: "recognition.settings.title",
      perm: READ,
      feature: "recognition",
      order: 58,
      icon: Trophy,
      component: defineAsyncComponent(() => lazy().then((m) => m.panels.settings())),
    },
  ],
  extensions: {
    "learning.person.panels": [defineAsyncComponent(() => lazy().then((m) => m.panels.person()))],
    "learning.overview.cards": [defineAsyncComponent(() => lazy().then((m) => m.panels.topLearners()))],
    "people.profile.actions": [defineAsyncComponent(() => lazy().then((m) => m.panels.sayThanks()))],
  },
  // `startapp=leaderboard` / `kudos` inside Telegram.
  deepLinks: {
    leaderboard: () => "recognition",
    kudos: () => "recognition/kudos",
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
