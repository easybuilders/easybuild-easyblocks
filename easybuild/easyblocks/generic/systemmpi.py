##
# Copyright 2015-2016 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for using (already installed/existing) system MPI instead of a full install via EasyBuild.

@author Alan O'Cais (Juelich Supercomputing Centre)
"""
import os
import re

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.tools.filetools import read_file, which
from easybuild.tools.run import run_cmd
from easybuild.framework.easyconfig.easyconfig import ActiveMNS
from easybuild.tools.build_log import EasyBuildError


class SystemMPI(Bundle):
    """
    Support for generating a module file for the system compiler with specified name.

    The compiler is expected to be available in $PATH, required libraries are assumed to be readily available.

    Specifying 'system' as a version leads to using the derived compiler version in the generated module;
    if an actual version is specified, it is checked against the derived version of the system compiler that was found.
    """

    def extract_ompi_version(self, txt):
        """Extract MPI version from provided string."""
        # look for 3-4 digit version number, surrounded by spaces
        # examples:
        # gcc (GCC) 4.4.7 20120313 (Red Hat 4.4.7-11)
        # Intel(R) C Intel(R) 64 Compiler XE for applications running on Intel(R) 64, Version 15.0.1.133 Build 20141023
        version_regex = re.compile(r'\s(v[0-9]+(?:\.[0-9]+){1,3})\s', re.M)
        res = version_regex.search(txt)
        if res:
            self.mpi_version = res.group(1)[1:]
            self.log.debug("Extracted MPI version '%s' from: %s", self.mpi_version, txt)
        else:
            raise EasyBuildError("Failed to extract OpenMPI version using regex pattern '%s' from: %s",
                                 version_regex.pattern, txt)

    def __init__(self, *args, **kwargs):
        """Extra initialization: determine system compiler version and prefix."""
        super(SystemMPI, self).__init__(*args, **kwargs)

        # Determine MPI path (real path, with resolved symlinks)
        mpi_name = self.cfg['name'].lower()
        mpi_c_compiler = 'mpicc'
        path_to_mpi_c_compiler = which(mpi_c_compiler)
        if path_to_mpi_c_compiler:
            path_to_mpi_c_compiler = os.path.realpath(path_to_mpi_c_compiler)
            self.log.info("Found path to MPI implementation '%s' mpicc compiler (with symlinks resolved): %s",
                          mpi_name, path_to_mpi_c_compiler)
        else:
            raise EasyBuildError("%s not found in $PATH", mpi_c_compiler)

        # Determine compiler version and installation prefix
        if mpi_name == 'openmpi':
            out, _ = run_cmd("ompi_info --version", simple=False)
            self.extract_ompi_version(out)

            # extract the installation prefix
            self.mpi_prefix, _ = run_cmd("ompi_info --path prefix|awk '{print $2}'", simple=False)
            # drop the carriage return
            self.mpi_prefix = self.mpi_prefix[:-1]
            # verify that toolchain compiler and compiler in MPI wrappers match
            #TODO

            # extract any OpenMPI environment variables in the current environment and ensure they are added to the
            # final module
            #TODO

        else:
            raise EasyBuildError("Unknown system MPI implementation %s", mpi_name)

        self.log.debug("Derived version/install prefix for system MPI %s: %s, %s",
                       mpi_name, self.mpi_version, self.mpi_prefix)

        # If EasyConfig specified "real" version (not 'system' which means 'derive automatically'), check it
        if self.cfg['version'] == 'system':
            self.log.info("Found specified version '%s', going with derived compiler version '%s'",
                          self.cfg['version'], self.mpi_version)
        elif self.cfg['version'] != self.mpi_version:
            raise EasyBuildError("Specified version (%s) does not match version reported by MPI (%s)" %
                                 (self.cfg['version'], self.mpi_version))

        # fix installdir and module names (may differ because of changes to version)
        mns = ActiveMNS()
        self.cfg.full_mod_name = mns.det_full_module_name(self.cfg)
        self.cfg.short_mod_name = mns.det_short_module_name(self.cfg)
        self.cfg.mod_subdir = mns.det_module_subdir(self.cfg)

        # keep track of original values, for restoring later
        self.orig_version = self.cfg['version']
        self.orig_installdir = self.installdir

    def make_installdir(self, dontcreate=None):
        """Custom implementation of make installdir: do nothing, do not touch system compiler directories and files."""
        pass

    def make_module_req_guess(self):
        """
        A dictionary of possible directories to look for.  Return empty dict for a system MPI.
        """
        return {}

    def make_module_step(self, fake=False):
        """
        Custom module step for SystemMPI: make 'EBROOT' and 'EBVERSION' reflect actual system MPI version
        and install path.
        """
        # For module file generation: temporarily set version and installdir to system compiler values
        self.cfg['version'] = self.mpi_version
        self.installdir = self.mpi_prefix

        # Generate module
        res = super(SystemMPI, self).make_module_step(fake=fake)

        # Reset version and installdir to EasyBuild values
        self.installdir = self.orig_installdir
        self.cfg['version'] = self.orig_version
        return res

    def make_module_extend_modpath(self):
        """
        Custom prepend-path statements for extending $MODULEPATH: use version specified in easyconfig file (e.g.,
        "system") rather than the actual version (e.g., "4.8.2").
        """
        # temporarily set switch back to version specified in easyconfig file (e.g., "system")
        self.cfg['version'] = self.orig_version

        # Retrieve module path extensions
        res = super(SystemMPI, self).make_module_extend_modpath()

        # Reset to actual compiler version (e.g., "4.8.2")
        self.cfg['version'] = self.mpi_version
        return res
