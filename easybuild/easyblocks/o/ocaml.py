##
# Copyright 2015-2025 Ghent University
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
EasyBuild support for building and installing OCaml + opam (+ extensions), implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import os
import re
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir
from easybuild.tools.run import run_shell_cmd


EXTS_FILTER_OCAML_PACKAGES = ("eval `opam config env` && opam list --installed %(ext_name)s.%(ext_version)s", '')
OPAM_SUBDIR = 'opam'


def det_opam_version():
    """Determine OPAM version (using 'opam --version')."""

    opam_ver = None

    opam_version_cmd = 'opam --version'
    res = run_shell_cmd(opam_version_cmd, fail_on_error=False)
    if res.exit_code == 0:
        ver_search = re.search('^[0-9.]+$', res.output.strip())
        if ver_search:
            opam_ver = ver_search.group(0)

    if opam_ver is None:
        raise EasyBuildError("Failed to determine OPAM version using '%s'!", opam_version_cmd)

    return opam_ver


def mk_opam_init_cmd(root=None):
    """Construct 'opam init' command."""

    opam_init_cmd = ['opam', 'init']

    if LooseVersion(det_opam_version()) >= LooseVersion('2.0.0'):
        # disable sandboxing, required bubblewrap (which requires setuid)
        # see http://opam.ocaml.org/doc/FAQ.html#Why-does-opam-require-bwrap
        opam_init_cmd.append('--disable-sandboxing')

    if root:
        opam_init_cmd.extend(['--root', root])

    return ' '.join(opam_init_cmd)


class EB_OCaml(ConfigureMake):
    """Support for building/installing OCaml + opam (+ additional extensions)."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for OCaml."""
        super(EB_OCaml, self).__init__(*args, **kwargs)
        self.with_opam = False

        # custom extra paths/variables to define in generated module for OCaml
        self.module_load_environment.CAML_LD_LIBRARY_PATH = ['lib']
        self.module_load_environment.OPAMROOT = [OPAM_SUBDIR]
        self.module_load_environment.PATH = ['bin', os.path.join(OPAM_SUBDIR, 'default', 'bin')]

    def configure_step(self):
        """Custom configuration procedure for OCaml."""
        self.cfg['prefix_opt'] = '-prefix '
        if LooseVersion(self.version) < LooseVersion("4.12"):
            self.cfg.update('configopts', '-cc "%s %s"' % (os.environ['CC'], os.environ['CFLAGS']))

        if 'world.opt' not in self.cfg['buildopts']:
            self.cfg.update('buildopts', 'world.opt')

        super(EB_OCaml, self).configure_step()

    def install_step(self):
        """
        Custom install procedure for OCaml.
        First install OCaml using 'make install', then install OPAM (if sources are provided).
        """
        super(EB_OCaml, self).install_step()

        try:
            all_dirs = os.listdir(self.builddir)
        except OSError as err:
            raise EasyBuildError("Failed to check contents of %s: %s", self.builddir, err)

        opam_dirs = [d for d in all_dirs if d.startswith('opam')]
        if len(opam_dirs) == 1:
            # load temporary module so OCaml installation is available for building & installing opam
            fake_mod_data = self.load_fake_module()

            opam_dir = os.path.join(self.builddir, opam_dirs[0])
            self.log.info("Found unpacked OPAM sources at %s, so installing it.", opam_dir)
            self.with_opam = True
            change_dir(opam_dir)

            run_shell_cmd("./configure --prefix=%s" % self.installdir)
            run_shell_cmd("make lib-ext")  # locally build/install required dependencies
            run_shell_cmd("make")
            run_shell_cmd("make install")

            opam_init_cmd = mk_opam_init_cmd(root=os.path.join(self.installdir, OPAM_SUBDIR))
            run_shell_cmd(opam_init_cmd)

            self.clean_up_fake_module(fake_mod_data)
        else:
            self.log.warning("OPAM sources not found in %s: %s", self.builddir, all_dirs)

    def prepare_for_extensions(self):
        """Set default class and filter for OCaml packages."""
        # build and install additional packages with OCamlPackage easyblock
        self.cfg['exts_defaultclass'] = "OCamlPackage"
        self.cfg['exts_filter'] = EXTS_FILTER_OCAML_PACKAGES
        super(EB_OCaml, self).prepare_for_extensions()

    def collect_exts_file_info(self, *args, **kwargs):
        """Don't fetch extension sources, OPAM takes care of that (and archiving too)."""
        return [{'name': ext_name, 'version': ext_version} for ext_name, ext_version in self.cfg['exts_list']]

    def sanity_check_step(self):
        """Custom sanity check for OCaml."""
        binaries = ['bin/ocaml', 'bin/ocamlc', 'bin/ocamlopt', 'bin/ocamlrun']
        dirs = []
        if self.with_opam:
            binaries.append('bin/opam')
            dirs.append(OPAM_SUBDIR)

        extension_names = [ext_name for ext_name, _ in self.cfg['exts_list']]

        custom_commands = ["ocaml --help"]
        if 'ocamlfind' in extension_names:
            custom_commands.append("ocamlfind list")

        if 'dune' in extension_names:
            custom_commands.append("dune --version")

        custom_paths = {
            'files': binaries,
            'dirs': dirs,
        }

        super(EB_OCaml, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
