##
# Copyright 2023-2024 Ghent University
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
import glob
import os
import re

from easybuild.easyblocks.generic.configuremake import ConfigureMake

from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


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

        # old llvm builds from CI get deleted after a certain time
        self.cfg.update('configopts', "--set=llvm.download-ci-llvm=false")

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

    def install_step(self):
        """Custom install step for Rust"""

        super(EB_Rust, self).install_step()

        if build_option('rpath'):
            # make sure that all shared libraries use RPATH, not RUNPATH;
            # cfr. https://github.com/easybuilders/easybuild-easyconfigs/issues/18079
            shlib_ext = get_shared_lib_ext()
            shared_libs = glob.glob(os.path.join(self.installdir, 'lib', 'lib*.%s' % shlib_ext))

            runpath_regex = re.compile(r"\(RUNPATH\)\s+Library runpath")

            for shared_lib in shared_libs:
                out, ec = run_cmd("readelf -d %s" % shared_lib, simple=False, trace=False)
                if ec:
                    raise EasyBuildError("Failed to check RPATH section in %s: %s", shared_lib, out)
                elif runpath_regex.search(out):
                    self.log.info("RUNPATH section found in %s - need to change to RPATH", shared_lib)

                    # first determine current RUNPATH value
                    out, ec = run_cmd("patchelf --print-rpath %s" % shared_lib)
                    if ec:
                        raise EasyBuildError("Failed to determine current RUNPATH value for %s: %s", shared_lib, out)
                    else:
                        runpath = out.strip()
                        # use RUNPATH value to RPATH value
                        out, ec = run_cmd("patchelf --set-rpath '%s' --force-rpath %s" % (runpath, shared_lib))
                        if ec:
                            raise EasyBuildError("Failed to set RPATH for %s: %s", shared_lib, out)
                        else:
                            self.log.info("RPATH set for %s", shared_lib)
                else:
                    self.log.info("No RUNPATH section found in %s", shared_lib)

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
