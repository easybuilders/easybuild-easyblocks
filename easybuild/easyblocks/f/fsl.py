##
# Copyright 2009-2023 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for building and installing FSL, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""

import difflib
import os
import re
from distutils.version import LooseVersion

import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd
from easybuild.tools.filetools import read_file, copy_dir
from easybuild.tools.utilities import nub


class EB_FSL(EasyBlock):
    """Support for building and installing FSL."""

    def __init__(self, *args, **kwargs):
        """Specify building in install dir, initialize custom variables."""

        super(EB_FSL, self).__init__(*args, **kwargs)

        self.build_in_installdir = True

        self.fsldir = None

    def configure_step(self):
        """Configure FSL build: set FSLDIR env var."""

        self.fsldir = self.cfg['start_dir']
        env.setvar('FSLDIR', self.fsldir)

        # determine FSL machine type
        cmd = ". %s/etc/fslconf/fslmachtype.sh" % self.fsldir
        (out, _) = run_cmd(cmd, log_all=True, simple=False)
        fslmachtype = out.strip()
        self.log.debug("FSL machine type: %s" % fslmachtype)

        best_cfg = None

        # Predefined makefiles for various configs have disappeared in v6.0.2.
        # The next part of the EasyBlock has thereby become obsolete.
        # See https://github.com/easybuilders/easybuild-easyblocks/issues/1859
        if LooseVersion(self.version) < LooseVersion('6.0.2'):

            # Patch files for ver. < 5.0.10 patch multiple config directories
            if LooseVersion(self.version) >= LooseVersion('5.0.10'):
                # Check if a specific machine type directory is patched
                systype_regex = re.compile(r"^diff.*config\/(.*(apple|gnu|i686|linux|spark)(?:(?!\/).)*)", re.M)

                patched_cfgs = []

                for patch in self.patches:
                    patchfile = read_file(patch['path'])
                    res = systype_regex.findall(patchfile)
                    patched_cfgs.extend([i[0] for i in res])

                # Check that at least one config has been found
                if patched_cfgs:
                    # Check that a single config has been patched
                    if len(nub(patched_cfgs)) == 1:
                        best_cfg = patched_cfgs[0]
                        self.log.debug("Found patched config dir: %s", best_cfg)
                    else:
                        raise EasyBuildError("Patch files are editing multiple config dirs: %s", patched_cfgs)
                else:
                    self.log.debug("No config dir found in patch files")

            # If no patched config is found, pick best guess
            cfgdir = os.path.join(self.fsldir, "config")
            try:
                if not best_cfg:
                    cfgs = os.listdir(cfgdir)
                    best_cfg = difflib.get_close_matches(fslmachtype, cfgs)[0]
                    self.log.debug("Best matching config dir for %s is %s" % (fslmachtype, best_cfg))
            except OSError as err:
                raise EasyBuildError("Unable to access configuration directory: %s", cfgdir, err)

            # Prepare config
            # Either use patched config or copy closest match
            if fslmachtype != best_cfg:
                srcdir = os.path.join(cfgdir, best_cfg)
                tgtdir = os.path.join(cfgdir, fslmachtype)
                copy_dir(srcdir, tgtdir)
                self.log.debug("Copied %s to %s" % (srcdir, tgtdir))

    def build_step(self):
        """Build FSL using supplied script."""

        cmd = ". %s/etc/fslconf/fsl.sh && ./build" % self.fsldir
        run_cmd(cmd, log_all=True, simple=True)

        # check build.log file for success
        buildlog = os.path.join(self.installdir, "fsl", "build.log")
        f = open(buildlog, "r")
        txt = f.read()
        f.close()

        error_regexp = re.compile("ERROR in BUILD")
        if error_regexp.search(txt):
            raise EasyBuildError("Error detected in build log %s.", buildlog)

    def install_step(self):
        """Building was performed in install dir, no explicit install step required."""
        pass

    def make_module_req_guess(self):
        """Set correct PATH and LD_LIBRARY_PATH variables."""

        guesses = super(EB_FSL, self).make_module_req_guess()

        guesses.update({
            'PATH': ["fsl/bin"],
            'LD_LIBRARY_PATH': ["fsl/lib"],
        })

        return guesses

    def make_module_extra(self):
        """Add setting of FSLDIR in module."""

        txt = super(EB_FSL, self).make_module_extra()

        txt += self.module_generator.set_environment("FSLDIR", os.path.join(self.installdir, 'fsl'))

        return txt

    def sanity_check_step(self):
        """Custom sanity check for FSL"""

        custom_paths = {
            'files': [],
            'dirs': ['fsl/%s' % x for x in ['bin', 'data', 'etc', 'extras', 'include', 'lib']],
        }

        super(EB_FSL, self).sanity_check_step(custom_paths=custom_paths)
