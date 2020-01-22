# This file contains constants and functions required to find and update
# config.guess files in a source tree.

import os
import re
import stat
from datetime import datetime

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.config import source_paths
from easybuild.tools.filetools import read_file, remove_file, verify_checksum
from easybuild.easyblocks import VERSION as EASYBLOCKS_VERSION
from easybuild.tools.filetools import CHECKSUM_TYPE_SHA256, adjust_permissions, compute_checksum, download_file
from easybuild.tools.build_log import print_warning

# download location & SHA256 for config.guess script
# note: if this is updated, don't forget to trash the cached download from generic/Configure/<eb_version>/!
CONFIG_GUESS_VERSION = '2018-08-29'
CONFIG_GUESS_URL_STUB = "https://git.savannah.gnu.org/gitweb/?p=config.git;a=blob_plain;f=config.guess;hb="
CONFIG_GUESS_COMMIT_ID = "59e2ce0e6b46bb47ef81b68b600ed087e14fdaad"
CONFIG_GUESS_SHA256 = "c02eb9cc55c86cfd1e9a794e548d25db5c9539e7b2154beb649bc6e2cbffc74c"


class ConfigGuessUpdater(EasyBlock):
    def __init__(self, *args, **kwargs):
        """Initialize easyblock."""
        super(ConfigGuessUpdater, self).__init__(*args, **kwargs)

        self.config_guess = None

    def fetch_step(self, *args, **kwargs):
        """Custom fetch step for ConfigGuessUpdater so we use an updated config.guess."""
        super(ConfigGuessUpdater, self).fetch_step(*args, **kwargs)

        # Use an updated config.guess from a global location (if possible)
        self.config_guess = self.obtain_config_guess()

    def obtain_config_guess(self, download_source_path=None, search_source_paths=None):
        """
        Locate or download an up-to-date config.guess for use with ConfigureMake

        :param download_source_path: Path to download config.guess to
        :param search_source_paths: Paths to search for config.guess
        :return: Path to config.guess or None
        """
        eb_source_paths = source_paths()
        if download_source_path is None:
            download_source_path = eb_source_paths[0]
        if search_source_paths is None:
            search_source_paths = eb_source_paths

        config_guess = 'config.guess'
        sourcepath_subdir = os.path.join('generic', 'eb_v%s' % EASYBLOCKS_VERSION, 'ConfigureMake')

        config_guess_path = None

        # check if config.guess has already been downloaded to source path
        for path in eb_source_paths:
            cand_config_guess_path = os.path.join(path, sourcepath_subdir, config_guess)
            if os.path.isfile(cand_config_guess_path):
                config_guess_path = cand_config_guess_path
                self.log.info("Found recent %s at %s, using it if required", config_guess, config_guess_path)
                break

        # if not found, try to download it
        if config_guess_path is None:
            cand_config_guess_path = os.path.join(download_source_path, sourcepath_subdir, config_guess)
            config_guess_url = CONFIG_GUESS_URL_STUB + CONFIG_GUESS_COMMIT_ID
            downloaded_path = download_file(config_guess, config_guess_url, cand_config_guess_path)
            if downloaded_path is not None:
                # verify SHA256 checksum of download to avoid using a corrupted download
                if verify_checksum(downloaded_path, CONFIG_GUESS_SHA256):
                    config_guess_path = downloaded_path
                    # add execute permissions
                    adjust_permissions(downloaded_path, stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH, add=True)
                    self.log.info("Downloaded recent %s to %s, using it if required", config_guess, config_guess_path)
                else:
                    self.log.warning("Checksum failed for downloaded file %s, not using it!", downloaded_path)
                    remove_file(downloaded_path)
            else:
                self.log.warning("Failed to download recent %s to %s for use with ConfigureMake easyblock (if needed)",
                                 config_guess, cand_config_guess_path)

        return config_guess_path

    def check_config_guess(self):
        """
        Check timestamp & SHA256 checksum of config.guess script.

        Returns True if ok (or there is no config.guess for this package) and False if it's too old
        or doesn't match the checksum.
        """
        # log version, timestamp & SHA256 checksum of config.guess that was found (if any)
        if self.config_guess:
            # config.guess includes a "timestamp='...'" indicating the version
            config_guess_version = None
            version_regex = re.compile("^timestamp='(.*)'", re.M)
            res = version_regex.search(read_file(self.config_guess))
            if res:
                config_guess_version = res.group(1)

            config_guess_checksum = compute_checksum(self.config_guess, checksum_type=CHECKSUM_TYPE_SHA256)
            try:
                config_guess_timestamp = datetime.fromtimestamp(os.stat(self.config_guess).st_mtime).isoformat()
            except OSError as err:
                self.log.warning("Failed to determine timestamp of %s: %s", self.config_guess, err)
                config_guess_timestamp = None

            self.log.info("config.guess version: %s (last updated: %s, SHA256 checksum: %s)",
                          config_guess_version, config_guess_timestamp, config_guess_checksum)

            if config_guess_version != CONFIG_GUESS_VERSION:
                tup = (self.config_guess, config_guess_version, CONFIG_GUESS_VERSION)
                print_warning("config.guess version at %s does not match expected version: %s vs %s" % tup)
                return False

            if config_guess_checksum != CONFIG_GUESS_SHA256:
                tup = (self.config_guess, config_guess_checksum, CONFIG_GUESS_SHA256)
                print_warning("SHA256 checksum of config.guess at %s does not match expected checksum: %s vs %s" % tup)
                return False

        return True
