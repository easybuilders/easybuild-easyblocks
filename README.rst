.. image:: http://hpcugent.github.io/easybuild/images/easybuild_logo_small.png
   :align: center

`EasyBuild <https://hpcugent.github.io/easybuild>`_ is a software build
and installation framework that allows you to manage (scientific) software
on High Performance Computing (HPC) systems in an efficient way.

The **easybuild-easyblocks** package provides a collection of *easyblocks* for
EasyBuild. Easyblocks are Python modules that implement the install procedure for a
(group of) software package(s). Together with the EasyBuild framework,
they allow to easily build and install supported software packages.

The EasyBuild documentation is available at http://easybuild.readthedocs.org/.

The easybuild-easyblocks source code is hosted on GitHub, along
with an issue tracker for bug reports and feature requests, see
http://github.com/hpcugent/easybuild-easyblocks.

Related Python packages:

* **easybuild-framework**

  * the EasyBuild framework, which includes the ``easybuild.framework`` and ``easybuild.tools`` Python
    packages that provide general support for building and installing software
  * GitHub repository: http://github.com/hpcugent/easybuild-framework
  * PyPi: https://pypi.python.org/pypi/easybuild-framework

* **easybuild-easyconfigs**

  * a collection of example easyconfig files that specify which software to build,
    and using which build options; these easyconfigs will be well tested
    with the latest compatible versions of the easybuild-framework and easybuild-easyblocks packages
  * GitHub repository: http://github.com/hpcugent/easybuild-easyconfigs
  * PyPi: https://pypi.python.org/pypi/easybuild-easyconfigs

*Build status overview:*

* **master** branch *(Python 2.4, Python 2.6, Python 2.7)*

  .. image:: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_master-python24/badge/icon
      :target: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_master-python24/
  .. image:: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_master/badge/icon
      :target: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_master/  
  .. image:: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_master-python27/badge/icon
      :target: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_master-python27/ 

* **develop** branch *(Python 2.4, Python 2.6, Python 2.7)*

  .. image:: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_develop-python24/badge/icon
      :target: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_develop-python24/  
  .. image:: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_develop/badge/icon
      :target: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_develop/  
  .. image:: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_develop-python27/badge/icon
      :target: https://jenkins1.ugent.be/view/EasyBuild/job/easybuild-easyblocks_unit-test_hpcugent_develop-python27/
