##
# Copyright 2023-2023 Ghent University
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
EasyBuild support for building and installing Rust, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake


class EB_Rust(ConfigureMake):
    """Support for building/installing Rust."""

    def __init__(self, *args, **kwargs):
        """Custom easyblock constructor for Rust."""
        super(EB_Rust, self).__init__(*args, **kwargs)

        # see https://rustc-dev-guide.rust-lang.org/building/how-to-build-and-run.html#what-is-xpy
        # note: ConfigureMake.build_step automatically adds '-j <parallel>'
        self.cfg['build_cmd'] = "./x.py build"
        self.cfg['install_cmd'] = "./x.py install -j %(parallel)s"

    def configure_step(self):
        """Custom configure step for Rust"""

        # perform extended build, which includes cargo, rustfmt, Rust Language Server (RLS), etc.
        self.cfg.update('configopts', "--enable-extended")

        self.cfg.update('configopts', "--sysconfdir=%s" % os.path.join(self.installdir, 'etc'))

        # don't use Ninja if it is not listed as a build dependency;
        # may be because Ninja requires Python, and Rust is a build dependency for cryptography
        # which may be included as an extension with Python
        build_dep_names = set(dep['name'] for dep in self.cfg.dependencies(build_only=True))
        if 'Ninja' not in build_dep_names:
            self.cfg.update('configopts', "--set=llvm.ninja=false")

        super(EB_Rust, self).configure_step()

        # avoid failure when home directory is an NFS mount,
        # see https://github.com/rust-lang/cargo/issues/6652
        cargo_home = "export CARGO_HOME=%s && " % os.path.join(self.builddir, 'cargo')
        self.cfg.update('prebuildopts', cargo_home)
        self.cfg.update('preinstallopts', cargo_home)

    def sanity_check_step(self):
        """Custom sanity check for Rust"""

        custom_paths = {
            'files': ['bin/cargo', 'bin/rustc', 'bin/rustdoc'],
            'dirs': ['lib/rustlib', 'share/doc', 'share/man'],
        }

        custom_commands = [
            "cargo --version",
            "rustc --version",
        ]
        return super(EB_Rust, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
