##
# This is an easyblock for EasyBuild, see https://github.com/easybuilders/easybuild
#
# Copyright:: Copyright 2015-2024 Juelich Supercomputing Centre, Germany
# Authors::   Bernd Mohr <b.mohr@fz-juelich.de>
#             Markus Geimer <m.geimer@fz-juelich.de>
# License::   3-clause BSD
#
# This work is based on experiences from the UNITE project
# http://apps.fz-juelich.de/unite/
##
"""
EasyBuild support for building and installing PDT, implemented as an easyblock

@author Bernd Mohr (Juelich Supercomputing Centre)
@author Markus Geimer (Juelich Supercomputing Centre)
@author Alexander Grund (TU Dresden)
"""

import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
import easybuild.tools.toolchain as toolchain
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import symlink


def find_arch_dir(install_dir):
    """
    Find architecture directory inside the install tree.

    For simplicity any top-level folder containing a bin and lib directory is collected
    Raises an error if multiple or none matching folders are found
    Returns the architecture specific folder
    """
    arch_dirs = []
    for entry in os.listdir(install_dir):
        full_path = os.path.join(install_dir, entry)
        # Only check directories which are not symlinks
        # E.g. on x86_64 there are symlinks craycnl, mic_linux, ... to x86_64
        if not os.path.isdir(full_path) or os.path.islink(full_path):
            continue
        if all(os.path.isdir(os.path.join(full_path, subdir)) for subdir in ['bin', 'lib']):
            arch_dirs.append(full_path)

    if not arch_dirs:
        raise EasyBuildError('Architecture specific directory not found in %s', install_dir)
    elif len(arch_dirs) != 1:
        raise EasyBuildError('Found multiple architecture specific directories: %s', ', '.join(arch_dirs))
    return arch_dirs[0]


class EB_PDT(ConfigureMake):
    """Support for building/installing PDT."""

    def configure_step(self):
        """Custom configuration procedure for PDT."""
        # custom prefix option for configure command
        self.cfg['prefix_opt'] = '-prefix='

        # determine values for compiler flags to use
        known_compilers = {
            # assume that system toolchain uses a system-provided GCC
            toolchain.SYSTEM: '-GNU',
            toolchain.GCC: '-GNU',
            toolchain.INTELCOMP: '-icpc',
            toolchain.PGI: '-pgCC',
        }
        comp_fam = self.toolchain.comp_family()
        try:
            compiler_opt = known_compilers[comp_fam]
        except KeyError:
            raise EasyBuildError("Compiler family not supported yet: %s" % comp_fam)
        self.cfg.update('configopts', compiler_opt)

        # PDT's configure script ignores CFLAGS/CXXFLAGS set in the environment,
        # but allows to pass in custom flags via configure option
        useropt = os.getenv('CXXFLAGS')
        if self.toolchain.options['pic']:
            useropt += ' -fPIC'
        self.cfg.update('configopts', '-useropt="%s"' % useropt)

        # Configure creates required subfolders in installdir, so create first (but only once, during first iteration)
        if self.iter_idx == 0:
            super(EB_PDT, self).make_installdir()

        super(EB_PDT, self).configure_step()

    def build_step(self):
        """Skip build step"""
        # `make install` runs `make all` which runs `make clean`, so no point in doing a make first
        pass

    def make_installdir(self):
        """Skip creating installation directory, already done in configure step"""
        pass

    def install_step(self):
        """Create symlinks into arch-specific directories"""

        if self.cfg['parallel']:
            self.cfg.update('installopts', '-j %s' % self.cfg['parallel'])

        super(EB_PDT, self).install_step()

        # Link arch-specific directories into prefix
        arch_dir = find_arch_dir(self.installdir)
        self.log.info('Found %s as architecture specific directory. Creating symlinks...', arch_dir)
        for subdir in ('bin', 'lib'):
            src = os.path.join(arch_dir, subdir)
            dst = os.path.join(self.installdir, subdir)
            if os.path.lexists(dst):
                self.log.info('Skipping creation of symlink %s as it already exists', dst)
            else:
                symlink(os.path.relpath(src, self.installdir), dst, use_abspath_source=False)

    def sanity_check_step(self):
        """Custom sanity check for PDT."""
        custom_paths = {
            'files': [os.path.join('bin', 'cparse'),
                      os.path.join('include', 'pdb.h'),
                      os.path.join('lib', 'libpdb.a')],
            'dirs': [],
        }
        super(EB_PDT, self).sanity_check_step(custom_paths=custom_paths)
