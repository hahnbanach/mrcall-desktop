// Custom afterSign hook that drives notarization via @electron/notarize
// directly. Works around an electron-builder 24.x quirk where the
// `mac.notarize` config block forwards only `teamId` to @electron/notarize
// and drops `appleId` / `appleIdPassword` — notarytool is then invoked
// without auth and Apple replies HTTP 401, which @electron/notarize
// surfaces as "Unexpected token 'E', \"Error: HTT\"... is not valid JSON".
//
// Reads the same secrets the rest of the workflow uses:
//   APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID
//
// Skips silently on non-darwin builds and when env vars are missing
// (so local dev `npm run dist:mac` without secrets still produces an
// unsigned/un-notarized dmg).

const { notarize } = require('@electron/notarize');

exports.default = async function notarizing(context) {
  const { electronPlatformName, appOutDir } = context;
  if (electronPlatformName !== 'darwin') return;

  const appleId = process.env.APPLE_ID;
  const appleIdPassword = process.env.APPLE_APP_SPECIFIC_PASSWORD;
  const teamId = process.env.APPLE_TEAM_ID;

  if (!appleId || !appleIdPassword || !teamId) {
    console.warn(
      '[notarize] APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID not set — skipping notarization (signed but un-notarized build)'
    );
    return;
  }

  const appName = context.packager.appInfo.productFilename;
  const appPath = `${appOutDir}/${appName}.app`;
  console.log(`[notarize] submitting ${appPath} — Apple typically takes 5–30 minutes`);

  return await notarize({
    tool: 'notarytool',
    appPath,
    appleId,
    appleIdPassword,
    teamId,
  });
};
