import packageMetadata from '../package.json';

/** The package manifest is the single source for the displayed application version. */
export const appVersionLabel = `v${packageMetadata.version} Beta`;
