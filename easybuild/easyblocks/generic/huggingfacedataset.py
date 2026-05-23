##
# Copyright 2009-2026 Ghent University
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
EasyBuild support for installing datasets

@author: Viktor Rehnberg (Chalmers University of Technology)
"""
import os

from easybuild.easyblocks.generic.dataset import Dataset
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.environment import restore_env_vars, setvar, unset_env_vars
from easybuild.tools.filetools import change_dir, clean_dir, expand_glob_paths, find_glob_pattern, mkdir, move_file
from easybuild.tools.filetools import write_file
from easybuild.tools.run import run_shell_cmd


class HuggingFaceDataset(Dataset):
    '''Support for installing datasets from huggingface.co'''

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Data easyblock."""
        extra_vars = Dataset.extra_options(extra_vars)
        extra_vars.update({
            'hf_name': [None, "Name of dataset on huggingface.co e.g. `uoft-cs/cifar10`", MANDATORY],
            'hf_revision': [None, "Version tag or commit hash on huggingface.co", MANDATORY],
            'extract_sources': [False, "Whether or not to extract data sources", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        '''Initialize HuggingFaceDataset-specific variables.'''
        super().__init__(*args, **kwargs)
        self.build_in_installdir = False

    def build_step(self):
        '''Build up cache_dir with dataset'''

        # Prepare download directory of cache_dir
        change_dir(self.builddir)
        mkdir('downloads')

        def _hash_url_to_filename(url):
            return run_shell_cmd(
                f'python -c "import datasets; print(datasets.utils.file_utils.hash_url_to_filename(\'{url}\'))"'
            ).output

        for src_spec in self.cfg['data_sources']:
            _url = f"hf://datasets/{self.cfg['hf_name']}@{self.cfg['hf_revision']}/{src_spec['filename']}"
            hash_filename = os.path.join(
                'downloads',
                _hash_url_to_filename(_url)
            )
            move_file(src_spec['filename'],  hash_filename)
            write_file(f"{hash_filename}.json", f'{{"url": "{_url}", "etag": null}}'.encode('utf-8'))

        # Build actual dataset
        old_env = unset_env_vars(['HF_HOME'])
        setvar('HF_HOME', os.path.join(self.builddir, 'hf_home'))
        try:
            load_arg_str = ", ".join([
                f"{key}='{val}'"
                for key, val in {
                    'path': self.cfg['hf_name'],
                    'revision': self.cfg['hf_revision'],
                    'cache_dir': self.builddir,
                    'download_mode': 'reuse_cache_if_exists',
                    'verification_mode': 'all_checks',
                }.items()
            ])
            run_shell_cmd(f'python -c "from datasets import load_dataset; load_dataset({load_arg_str})"')
        finally:
            restore_env_vars(old_env)

        # Clean-up
        clean_dir('hf_home')
        clean_dir('downloads')

    def install_step(self):
        '''Move actual dataset directory to installdir'''
        change_dir(self.installdir)
        dataset_dir = os.path.dirname(
            find_glob_pattern(
                os.path.join(
                    self.builddir,
                    self.cfg['hf_name'].replace('/', '___'),
                    '*',  # default
                    '*',  # version string
                    '*',  # commit hash
                    'dataset_info.json',
                )
            )
        )
        for dataset_file in expand_glob_paths([os.path.join(dataset_dir, '*')]):
            move_file(dataset_file, os.path.join(self.installdir, os.path.basename(dataset_file)))
