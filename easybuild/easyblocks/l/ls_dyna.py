##
# Copyright 2009-2021 Ghent University
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
EasyBlock for LS-DYNA

@author: James Carpenter (University of Birmingham)
"""
import os
import re

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd


class EB_LS_minus_DYNA(EasyBlock):
    """Support for installing packed binary software.
    Just unpack the sources in the install dir
    """

    def __init__(self, *args, **kwargs):
        """Constructor, adds extra class variables."""
        super(EB_LS_minus_DYNA, self).__init__(*args, **kwargs)
        self.build_sources = []

    def extract_step(self):
        """Unpack the source"""
        EasyBlock.extract_step(self)

    def configure_step(self):
        """No configuration, this is binary software"""
        pass

    def build_step(self):
        """No compilation, this is binary software"""
        pass

    def install_step(self):
        """Install the SMP versions and the best matches for MPP versions"""
        # Find CPU info
        cmd = "cat /proc/cpuinfo"
        (cpuinfo, _) = run_cmd(cmd, log_all=True, simple=False)
        # List capabilities to check against. N.B. order is important!
        cpu_caps_regex = [r"avx512", r"avx2", r"sse2"]
        best_cpu_caps = None
        for regex in cpu_caps_regex:
            if re.search(regex, cpuinfo):
                best_cpu_caps = regex
                # Exit loop as soon as we match
                break
        if not best_cpu_caps:
            raise EasyBuildError("Unable to determine best vectorisation capabilities for cpu")
        try:
            for src in os.listdir(self.builddir):
                srcpath = os.path.join(self.builddir, src)
                if os.path.isfile(srcpath):
                    # Check if SMP first, continuing as appopriate
                    if re.search(r"smp", srcpath):
                        self.build_sources.append(srcpath)
                        continue
                    elif re.search(best_cpu_caps, srcpath):
                        self.build_sources.append(srcpath)
                        # Don't check anymore cpu_caps as we only want the best fits
                        continue
                else:
                    raise EasyBuildError("Path %s is not a file", srcpath)
            if len(self.build_sources) > 0:
                for src in self.build_sources:
                    install_cmd = f"sh {src} --prefix={self.installdir} --skip-license --exclude-subdir"
                    run_cmd(install_cmd, log_all=True, simple=True)
            else:
                raise EasyBuildError("Could not locate any files to install")
        except OSError as err:
            raise EasyBuildError("Failed to install unpacked sources into install directory: %s", err)

    def sanity_check_step(self):
        """Custom sanity check for LS-DYNA."""
        # Create a list of installed binaries
        installed_bins = [f"./{os.path.basename(binpath).split('.')[0]}" for binpath in self.build_sources]
        custom_paths = {
            'files': installed_bins,
            'dirs': [],
        }
        super(EB_LS_minus_DYNA, self).sanity_check_step(custom_paths=custom_paths)
