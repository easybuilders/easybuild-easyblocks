##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for installing COMSOL, implemented as an easyblock

@author: Mikael OEhman (Chalmers University of Technology)
@author: Ake Sandgren (HPC2N, Umea University)
"""
import os
import re
import stat

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, copy_file, find_flexlm_license, read_file, write_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_COMSOL(PackedBinary):
    """Support for installing COMSOL."""

    def __init__(self, *args, **kwargs):
        """Add extra config options specific to COMSOL."""
        super(EB_COMSOL, self).__init__(*args, **kwargs)
        self.configfile = os.path.join(self.builddir, 'my_setupconfig.ini')

    def extract_step(self):
        """Need to adjust the permissions on the top dir, the DVD has 0444."""
        super(EB_COMSOL, self).extract_step()

        # The tar file comes from the DVD and has 0444 as permission at the top dir.
        adjust_permissions(self.builddir, stat.S_IWUSR)

    def configure_step(self):
        """Configure COMSOL installation: create license file."""

        comsol_lic_env_vars = ['EB_COMSOL_LICENSE_FILE', 'LMCOMSOL_LICENSE_FILE']
        lic_specs, self.license_env_var = find_flexlm_license(custom_env_vars=comsol_lic_env_vars,
                                                              lic_specs=[self.cfg['license_file']])

        if lic_specs:
            if self.license_env_var is None:
                self.log.info("Using COMSOL license specifications from 'license_file': %s", lic_specs)
                self.license_env_var = comsol_lic_env_vars[0]
            else:
                self.log.info("Using COMSOL license specifications from $%s: %s", self.license_env_var, lic_specs)

            self.license_file = os.pathsep.join(lic_specs)
            env.setvar(self.license_env_var, self.license_file)
        else:
            msg = "No viable license specifications found; "
            msg += "specify 'license_file', or define %s" % (', '.join('$%s' % x for x in comsol_lic_env_vars))
            raise EasyBuildError(msg)

        copy_file(os.path.join(self.start_dir, 'setupconfig.ini'), self.configfile)
        config = read_file(self.configfile)

        config_vars = {
            'agree': '1',
            'desktopshortcuts': '0',
            'fileassoc': '0',
            'firewall': '0',
            'installdir': self.installdir,
            'license': self.license_file,
            'licmanager': '0',
            'linuxlauncher': '0',
            'showgui': '0',
            'startmenushortcuts': '0',
            'symlinks': '0',
        }

        matlab_root = get_software_root("MATLAB")
        if matlab_root:
            config_vars.update({'matlabdir': matlab_root})

        for key, val in config_vars.items():
            regex = re.compile(r"^%s\s*=.*" % key, re.M)
            config = regex.sub("%s=%s" % (key, val), config)

        write_file(self.configfile, config)

        self.log.debug('configuration file written to %s:\n %s', self.configfile, config)

    def install_step(self):
        """COMSOL install procedure using 'install' command."""

        setup_script = os.path.join(self.start_dir, 'setup')

        # make sure setup script is executable
        adjust_permissions(setup_script, stat.S_IXUSR)

        # make sure binaries in arch bindir is executable
        archpath = os.path.join(self.start_dir, 'bin', 'glnxa64')
        adjust_permissions(os.path.join(archpath, 'inflate'), stat.S_IXUSR)
        adjust_permissions(os.path.join(archpath, 'setuplauncher'), stat.S_IXUSR)

        # make sure $DISPLAY is not defined, which may lead to (hard to trace) problems
        # this is a workaround for not being able to specify --nodisplay to the install scripts
        env.unset_env_vars(['DISPLAY'])

        cmd = ' '.join([self.cfg['preinstallopts'], setup_script, '-s', self.configfile, self.cfg['installopts']])
        run_cmd(cmd, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for COMSOL."""
        custom_paths = {
            'files': [
                "bin/comsol", "bin/glnxa64/comsol",
                "lib/glnxa64/libcscomsolgeom.%s" % get_shared_lib_ext(),
            ],
            'dirs': ["java/glnxa64", "plugins"],
        }
        super(EB_COMSOL, self).sanity_check_step(custom_paths=custom_paths)
