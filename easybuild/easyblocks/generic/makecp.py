##
# Copyright 2013-2024 the Cyprus Institute
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
@author: George Tsouloupas (The Cyprus Institute)
@author: Fotis Georgatos (Uni.Lu, NTUA)
@author: Kenneth Hoste (Ghent University)
@author: Maxime Boissonneault (Digital Research Alliance of Canada, Universite Laval)
"""
import os
import glob

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import BUILD, MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, copy_dir, copy_file, mkdir
from easybuild.tools.py2vs3 import string_type


class MakeCp(ConfigureMake):
    """
    Software with no configure and no make install step.
    """
    @staticmethod
    def extra_options(extra_vars=None):
        """
        Define list of files or directories to be copied after make
        """
        extra = {
            'files_to_copy': [None, "List of files or dirs to copy", MANDATORY],
            'with_configure': [False, "Run configure script before building", BUILD],
        }
        if extra_vars is None:
            extra_vars = {}
        extra.update(extra_vars)
        return ConfigureMake.extra_options(extra_vars=extra)

    def configure_step(self, cmd_prefix=''):
        """
        Configure build if required
        """
        if self.cfg.get('with_configure', False):
            return super(MakeCp, self).configure_step(cmd_prefix=cmd_prefix)

    def install_step(self):
        """Install by copying specified files and directories."""

        # make sure we're (still) in the start dir
        change_dir(self.cfg['start_dir'])

        files_to_copy = self.cfg.get('files_to_copy') or []
        self.log.debug("Starting install_step with files_to_copy: %s", files_to_copy)

        # if this is an iterative build directories will be copied multiple times
        dirs_exist_ok = True if self.iter_opts else False

        for fil in files_to_copy:
            if isinstance(fil, tuple):
                # ([src1, src2], targetdir)
                if len(fil) == 2 and isinstance(fil[0], list) and isinstance(fil[1], string_type):
                    files_specs = fil[0]
                    target = os.path.join(self.installdir, fil[1])
                else:
                    raise EasyBuildError("Only tuples of format '([<source files>], <target dir>)' supported.")
            # 'src_file' or 'src_dir'
            elif isinstance(fil, string_type):
                files_specs = [fil]
                target = self.installdir
            else:
                raise EasyBuildError("Found neither string nor tuple as file to copy: '%s' (type %s)", fil, type(fil))

            mkdir(target, parents=True)

            for orig_files_spec in files_specs:
                if isinstance(orig_files_spec, tuple):
                    files_spec = orig_files_spec[0]
                    dest = orig_files_spec[1]
                else:
                    files_spec = orig_files_spec
                    dest = None

                # first look for files in start dir
                filepaths = glob.glob(os.path.join(self.cfg['start_dir'], files_spec))
                tup = (files_spec, self.cfg['start_dir'], filepaths)
                self.log.debug("List of files matching '%s' in start dir %s: %s" % tup)

                if not filepaths and len(self.src) > 0 and 'finalpath' in self.src[0]:
                    # use location of first unpacked source file as fallback location
                    tup = (files_spec, self.cfg['start_dir'])
                    self.log.warning("No files matching '%s' found in start dir %s" % tup)
                    filepaths = glob.glob(os.path.join(self.src[0]['finalpath'], files_spec))
                    self.log.debug("List of files matching '%s' in %s: %s" % (tup + (filepaths,)))

                # there should be at least one match per file spec
                if not filepaths:
                    raise EasyBuildError("No files matching '%s' found anywhere.", files_spec)

                if dest and len(filepaths) != 1:
                    raise EasyBuildError("When a list with new names has been specified, the original file spec can "
                                         "only match a single file yet it gives: %s", filepaths)

                for filepath in filepaths:
                    # copy individual file
                    if os.path.isfile(filepath):
                        if dest:
                            target_dest = os.path.join(target, dest)
                        else:
                            target_dest = target
                        self.log.debug("Copying file %s to %s", filepath, target_dest)
                        copy_file(filepath, target_dest)
                    # copy directory
                    elif os.path.isdir(filepath):
                        self.log.debug("Copying directory %s to %s", filepath, target)
                        fulltarget = os.path.join(target, os.path.basename(filepath))
                        copy_dir(filepath, fulltarget, symlinks=self.cfg['keepsymlinks'], dirs_exist_ok=dirs_exist_ok)
                    else:
                        raise EasyBuildError("Can't copy non-existing path %s to %s", filepath, target)
