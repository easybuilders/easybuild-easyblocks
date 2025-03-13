##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for installing a bundle of modules, implemented as a generic easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Jasper Grimm (University of York)
@author: Jan Andre Reuter (Juelich Supercomputing Centre)
"""
import copy
import os

import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.easyconfig.easyconfig import get_easyblock_class
from easybuild.tools.build_log import EasyBuildError, print_msg
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.utilities import nub


class Bundle(EasyBlock):
    """
    Bundle of modules: only generate module files, nothing to build/install
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to bundles."""
        if extra_vars is None:
            extra_vars = {}
        extra_vars.update({
            'altroot': [None, "Software name of dependency to use to define $EBROOT for this bundle", CUSTOM],
            'altversion': [None, "Software name of dependency to use to define $EBVERSION for this bundle", CUSTOM],
            'default_component_specs': [{}, "Default specs to use for every component", CUSTOM],
            'components': [(), "List of components to install: tuples w/ name, version and easyblock to use", CUSTOM],
            'sanity_check_components': [[], "List of components for which to run sanity checks", CUSTOM],
            'sanity_check_all_components': [False, "Enable sanity checks for all components", CUSTOM],
            'default_easyblock': [None, "Default easyblock to use for components", CUSTOM],
        })
        return EasyBlock.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize easyblock."""
        super(Bundle, self).__init__(*args, **kwargs)
        self.altroot = None
        self.altversion = None

        # list of EasyConfig instances and their EasyBlocks for components
        self.comp_instances = []

        # list of EasyConfig instances of components for which to run sanity checks
        self.comp_cfgs_sanity_check = []

        check_for_sources = getattr(self, 'check_for_sources', True)
        # list of sources for bundle itself *must* be empty (unless overridden by subclass)
        if check_for_sources:
            if self.cfg.get_ref('sources'):
                raise EasyBuildError("List of sources for bundle itself must be empty, found %s", self.cfg['sources'])
            if self.cfg.get_ref('patches'):
                raise EasyBuildError("List of patches for bundle itself must be empty, found %s", self.cfg['patches'])

        # copy EasyConfig instance before we make changes to it
        # (like adding component sources to top-level sources easyconfig parameter)
        self.cfg = self.cfg.copy()

        # disable templating to avoid premature resolving of template values
        # Note that self.cfg.update also resolves templates!
        with self.cfg.disable_templating():
            # list of checksums for patches (must be included after checksums for sources)
            checksums_patches = []

            if self.cfg['sanity_check_components'] and self.cfg['sanity_check_all_components']:
                raise EasyBuildError("sanity_check_components and sanity_check_all_components"
                                     "cannot be enabled together")

            # backup and reset general sanity checks from main body of ec,
            # if component-specific sanity checks are enabled necessary to avoid:
            # - duplicating the general sanity check across all components running sanity checks
            # - general sanity checks taking precedence over those defined in a component's easyblock
            self.backup_sanity_paths = self.cfg['sanity_check_paths']
            self.backup_sanity_cmds = self.cfg['sanity_check_commands']
            if self.cfg['sanity_check_components'] or self.cfg['sanity_check_all_components']:
                # reset general sanity checks, to be restored later
                self.cfg['sanity_check_paths'] = {}
                self.cfg['sanity_check_commands'] = {}
            components = self.cfg['components']

            for comp in components:
                comp_name, comp_version, comp_specs = comp[0], comp[1], {}
                if len(comp) == 3:
                    comp_specs = comp[2]

                comp_cfg = self.cfg.copy()

                comp_cfg['name'] = comp_name
                comp_cfg['version'] = comp_version

                # determine easyblock to use for this component
                # - if an easyblock is specified explicitely, that will be used
                # - if not, a software-specific easyblock will be considered by get_easyblock_class
                # - if no easyblock was found, default_easyblock is considered
                comp_easyblock = comp_specs.get('easyblock')
                easyblock_class = get_easyblock_class(comp_easyblock, name=comp_name, error_on_missing_easyblock=False)
                if easyblock_class is None:
                    if self.cfg['default_easyblock']:
                        easyblock = self.cfg['default_easyblock']
                        easyblock_class = get_easyblock_class(easyblock)

                    if easyblock_class is None:
                        raise EasyBuildError("No easyblock found for component %s v%s", comp_name, comp_version)
                    self.log.info("Using default easyblock %s for component %s", easyblock, comp_name)
                else:
                    easyblock = easyblock_class.__name__
                    self.log.info("Using easyblock %s for component %s", easyblock, comp_name)

                if easyblock == 'Bundle':
                    raise EasyBuildError("The Bundle easyblock can not be used to install components in a bundle")

                comp_cfg.easyblock = easyblock_class

                # make sure that extra easyconfig parameters are known, so they can be set
                extra_opts = comp_cfg.easyblock.extra_options()
                comp_cfg.extend_params(copy.deepcopy(extra_opts))

                comp_cfg.generate_template_values()

                # do not inherit easyblock to use from parent
                # (since that would result in an infinite loop in install_step)
                comp_cfg['easyblock'] = None

                # reset list of sources/source_urls/checksums
                comp_cfg['sources'] = comp_cfg['source_urls'] = comp_cfg['checksums'] = comp_cfg['patches'] = []

                for key in self.cfg['default_component_specs']:
                    comp_cfg[key] = self.cfg['default_component_specs'][key]

                for key in comp_specs:
                    comp_cfg[key] = comp_specs[key]

                # Don't require that all template values can be resolved at this point but still resolve them.
                # This is important to ensure that template values like %(name)s and %(version)s
                # are correctly resolved with the component name/version before values are copied over to self.cfg
                with comp_cfg.allow_unresolved_templates():
                    comp_sources = comp_cfg['sources']
                    comp_source_urls = comp_cfg['source_urls']
                if not comp_sources:
                    raise EasyBuildError("No sources specification for component %s v%s", comp_name, comp_version)
                # If per-component source URLs are provided, attach them directly to the relevant sources
                if comp_source_urls:
                    for source in comp_sources:
                        if isinstance(source, str):
                            self.cfg.update('sources', [{'filename': source, 'source_urls': comp_source_urls[:]}])
                        elif isinstance(source, dict):
                            # Update source_urls in the 'source' dict to use the one for the components
                            # (if it doesn't already exist)
                            if 'source_urls' not in source:
                                source['source_urls'] = comp_source_urls[:]
                            self.cfg.update('sources', [source])
                        else:
                            raise EasyBuildError("Source %s for component %s is neither a string nor a dict, cannot "
                                                 "process it.", source, comp_cfg['name'])
                else:
                    # add component sources to list of sources
                    self.cfg.update('sources', comp_sources)

                comp_checksums = comp_cfg['checksums']
                if comp_checksums:
                    src_cnt = len(comp_sources)

                    # add per-component checksums for sources to list of checksums
                    self.cfg.update('checksums', comp_checksums[:src_cnt])

                    # add per-component checksums for patches to list of checksums for patches
                    checksums_patches.extend(comp_checksums[src_cnt:])

                with comp_cfg.allow_unresolved_templates():
                    comp_patches = comp_cfg['patches']
                if comp_patches:
                    self.cfg.update('patches', comp_patches)

                self.comp_instances.append((comp_cfg, comp_cfg.easyblock(comp_cfg, logfile=self.logfile)))

            self.cfg.update('checksums', checksums_patches)

        # restore general sanity checks if using component-specific sanity checks
        if self.cfg['sanity_check_components'] or self.cfg['sanity_check_all_components']:
            self.cfg['sanity_check_paths'] = self.backup_sanity_paths
            self.cfg['sanity_check_commands'] = self.backup_sanity_cmds

    def check_checksums(self):
        """
        Check whether a SHA256 checksum is available for all sources & patches (incl. extensions).

        :return: list of strings describing checksum issues (missing checksums, wrong checksum type, etc.)
        """
        checksum_issues = super(Bundle, self).check_checksums()

        for comp, _ in self.comp_instances:
            checksum_issues.extend(self.check_checksums_for(comp, sub="of component %s" % comp['name']))

        return checksum_issues

    def patch_step(self):
        """Patch step must be a no-op for bundle, since there are no top-level sources/patches."""
        pass

    def get_altroot_and_altversion(self):
        """Get altroot and altversion, if they are defined"""
        altroot = None
        if self.cfg['altroot']:
            altroot = get_software_root(self.cfg['altroot'])
        altversion = None
        if self.cfg['altversion']:
            altversion = get_software_version(self.cfg['altversion'])
        return altroot, altversion

    def configure_step(self):
        """Collect altroot/altversion info."""
        self.altroot, self.altversion = self.get_altroot_and_altversion()

    def build_step(self):
        """Do nothing."""
        pass

    def install_step(self):
        """Install components, if specified."""
        comp_cnt = len(self.cfg['components'])
        for idx, (cfg, comp) in enumerate(self.comp_instances):

            print_msg("installing bundle component %s v%s (%d/%d)..." %
                      (cfg['name'], cfg['version'], idx + 1, comp_cnt))
            self.log.info("Installing component %s v%s using easyblock %s", cfg['name'], cfg['version'], cfg.easyblock)

            # correct build/install dirs
            comp.builddir = self.builddir
            comp.install_subdir, comp.installdir = self.install_subdir, self.installdir

            # make sure we can build in parallel
            comp.set_parallel()

            # figure out correct start directory
            comp.guess_start_dir()

            # need to run fetch_patches to ensure per-component patches are applied
            comp.fetch_patches()

            comp.src = []

            # find matching entries in self.src for this component
            with comp.cfg.allow_unresolved_templates():
                comp_sources = comp.cfg['sources']
            for source in comp_sources:
                if isinstance(source, str):
                    comp_src_fn = source
                elif isinstance(source, dict):
                    if 'filename' in source:
                        comp_src_fn = source['filename']
                    else:
                        raise EasyBuildError("Encountered source file specified as dict without 'filename': %s", source)
                else:
                    raise EasyBuildError("Specification of unknown type for source file: %s", source)

                found = False
                for src in self.src:
                    if src['name'] == comp_src_fn:
                        self.log.info("Found spec for source %s for component %s: %s", comp_src_fn, comp.name, src)
                        comp.src.append(src)
                        found = True
                        break
                if not found:
                    raise EasyBuildError("Failed to find spec for source %s for component %s", comp_src_fn, comp.name)

                # location of first unpacked source is used to determine where to apply patch(es)
                comp.src[-1]['finalpath'] = comp.cfg['start_dir']

            # check if sanity checks are enabled for the component
            if self.cfg['sanity_check_all_components'] or comp.cfg['name'] in self.cfg['sanity_check_components']:
                self.comp_cfgs_sanity_check.append(comp)

            # run relevant steps
            for step_name in ['patch', 'configure', 'build', 'install']:
                if step_name in cfg['skipsteps']:
                    comp.log.info("Skipping '%s' step for component %s v%s", step_name, cfg['name'], cfg['version'])
                else:
                    comp.run_step(step_name, [lambda x: getattr(x, '%s_step' % step_name)])

            if comp.make_module_req_guess.__qualname__ != 'EasyBlock.make_module_req_guess':
                depr_msg = f"Easyblock used to install component {comp.name} still uses make_module_req_guess"
                self.log.deprecated(depr_msg, '6.0')
                # update environment to ensure stuff provided by former components can be picked up by latter components
                # once the installation is finalised, this is handled by the generated module
                reqs = comp.make_module_req_guess()
                for envvar in reqs:
                    curr_val = os.getenv(envvar, '')
                    curr_paths = curr_val.split(os.pathsep)
                    for subdir in reqs[envvar]:
                        path = os.path.join(self.installdir, subdir)
                        if path not in curr_paths:
                            if curr_val:
                                new_val = '%s:%s' % (path, curr_val)
                            else:
                                new_val = path
                            env.setvar(envvar, new_val)
            else:
                # Update current environment with component environment to ensure stuff provided
                # by this component can be picked up by installation of subsequent components
                # - this is a stripped down version of EasyBlock.make_module_req for fake modules
                # - once bundle installation is complete, this is handled by the generated module as usual
                for mod_envar, mod_paths in comp.module_load_environment.items():
                    # expand glob patterns in module load environment to existing absolute paths
                    mod_expand = [x for p in mod_paths for x in comp.expand_module_search_path(p, False)]
                    mod_expand = nub(mod_expand)
                    mod_expand = [os.path.join(self.installdir, path) for path in mod_expand]
                    # prepend to current environment variable if new stuff added to installation
                    curr_env = os.getenv(mod_envar, '')
                    curr_paths = [path for path in curr_env.split(os.pathsep) if path]
                    new_paths = nub(mod_expand + curr_paths)
                    new_env = os.pathsep.join(new_paths)
                    if new_env and new_env != curr_env:
                        env.setvar(mod_envar, new_env)

    def make_module_step(self, *args, **kwargs):
        """
        Set module requirements from all components, e.g. $PATH, etc.
        During the install step, we only set these requirements temporarily.
        Later on when building the module, those paths are not considered.
        Therefore, iterate through all the components again and gather
        the requirements.

        Do not remove duplicates or check for existence of folders,
        as this is done in the generic EasyBlock while creating
        the module file already.
        """
        for cfg, comp in self.comp_instances:
            self.log.info("Gathering module paths for component %s v%s", cfg['name'], cfg['version'])

            # take into account that easyblock used for component may not be migrated yet to module_load_environment
            if comp.make_module_req_guess.__qualname__ != 'EasyBlock.make_module_req_guess':

                depr_msg = f"Easyblock used to install component {cfg['name']} still uses make_module_req_guess"
                self.log.deprecated(depr_msg, '6.0')

                reqs = comp.make_module_req_guess()

                # Try-except block to fail with an easily understandable error message.
                # This should only trigger when an EasyBlock returns non-dict module requirements
                # for make_module_req_guess() which should then be fixed in the components EasyBlock.
                try:
                    for key, value in sorted(reqs.items()):
                        if key in self.module_load_environment:
                            getattr(self.module_load_environment, key).extend(value)
                        else:
                            setattr(self.module_load_environment, key, value)
                except AttributeError:
                    raise EasyBuildError("Cannot process module requirements of bundle component %s v%s",
                                         cfg['name'], cfg['version'])
            else:
                for env_var_name, env_var_val in comp.module_load_environment.items():
                    if env_var_name in self.module_load_environment:
                        getattr(self.module_load_environment, env_var_name).extend(env_var_val)
                    else:
                        setattr(self.module_load_environment, env_var_name, env_var_val)

        return super().make_module_step(*args, **kwargs)

    def make_module_extra(self, *args, **kwargs):
        """Set extra stuff in module file, e.g. $EBROOT*, $EBVERSION*, etc."""
        if not self.altroot and not self.altversion:
            # check for altroot and altversion (needed here for a module only build)
            self.altroot, self.altversion = self.get_altroot_and_altversion()
        if 'altroot' not in kwargs:
            kwargs['altroot'] = self.altroot
        if 'altversion' not in kwargs:
            kwargs['altversion'] = self.altversion
        return super(Bundle, self).make_module_extra(*args, **kwargs)

    def sanity_check_step(self, *args, **kwargs):
        """
        If component sanity checks are enabled, run sanity checks for the desired components listed.
        If nothing is being installed, just being able to load the (fake) module is sufficient
        """
        if self.cfg['exts_list'] or self.cfg['sanity_check_paths'] or self.cfg['sanity_check_commands']:
            super(Bundle, self).sanity_check_step(*args, **kwargs)
        else:
            self.log.info("Testing loading of module '%s' by means of sanity check" % self.full_mod_name)
            fake_mod_data = self.load_fake_module(purge=True)
            self.log.debug("Cleaning up after testing loading of module")
            self.clean_up_fake_module(fake_mod_data)

        # run sanity checks for specific components
        cnt = len(self.comp_cfgs_sanity_check)
        for idx, comp in enumerate(self.comp_cfgs_sanity_check):
            comp_name, comp_ver = comp.cfg['name'], comp.cfg['version']
            print_msg("sanity checking bundle component %s v%s (%i/%i)...", comp_name, comp_ver, idx + 1, cnt)
            self.log.info("Starting sanity check step for component %s v%s", comp_name, comp_ver)

            comp.run_step('sanity_check', [lambda x: x.sanity_check_step])
