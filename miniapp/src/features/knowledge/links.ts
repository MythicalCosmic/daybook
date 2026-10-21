import { appScreenLink, resolveScreen } from "../../state/deeplink";
import { useNavigation, type Navigation, type NavigationInit } from "../../state/navigation";
import { openLink, openTelegramLink } from "../../telegram";
import { useFeatureContext } from "../hosts";
import { features, visibleFeatures } from "../registry";

/** Open the screen a link points to over the page that holds the link, so Back returns to it. */
function follow(navigation: Navigation, target: NavigationInit): void {
  if (target.stack?.length) {
    for (const page of target.stack) navigation.push(page);
    if (target.sheet) navigation.openSheet(target.sheet);
  } else if (target.sheet) {
    navigation.openSheet(target.sheet);
  } else {
    navigation.reset(target);
  }
}

/**
 * Where a link in a page's body goes: a link into this app opens its screen right here (in a
 * browser nobody would be signed in), a t.me link in Telegram, any other web link in Telegram's
 * own browser. Returns false for what it leaves to the web view (mail and phone links).
 */
export function useFollowLink(): (href: string) => boolean {
  const navigation = useNavigation();
  const context = useFeatureContext();
  return (href) => {
    if (!/^https?:/i.test(href)) return false;
    const link = appScreenLink(href);
    if (link) {
      const target = resolveScreen(link, features, visibleFeatures(features, context));
      if (target) follow(navigation, target);
      return true;
    }
    if (/^(www\.)?t\.me$/i.test(new URL(href).hostname)) openTelegramLink(href);
    else openLink(href);
    return true;
  };
}
