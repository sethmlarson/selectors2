import os
import re
from setuptools import setup

# Get the version (borrowed from SQLAlchemy)
base_path = os.path.dirname(__file__)
with open(os.path.join(base_path, 'selectors2.py')) as f:
    VERSION = re.compile(r'.*__version__ = \'(.*?)\'', re.S).match(f.read()).group(1)

with open('README.rst') as f:
    long_description = f.read()

with open('CHANGELOG.rst') as f:
    changelog = f.read()

if __name__ == '__main__':
    setup(name='selectors2',
          description='Back-ported, durable, and portable selectors',
          long_description=long_description + '\n\n' + changelog,
          license='MIT',
          url='https://www.github.com/sethmlarson/selectors2',
          version=VERSION,
          author='Seth Michael Larson',
          author_email='sethmichaellarson@gmail.com',
          maintainer='Seth Michael Larson',
          maintainer_email='sethmichaellarson@gmail.com',
          install_requires=[],
          keywords=['async', 'file', 'socket', 'select', 'backport'],
          py_modules=['selectors2'],
          zip_safe=False,
          classifiers=['Programming Language :: Python :: 2',
                       'Programming Language :: Python :: 2.6',
                       'Programming Language :: Python :: 2.7',
                       'Programming Language :: Python :: 3',
                       'Programming Language :: Python :: 3.3',
                       'Programming Language :: Python :: 3.4',
                       'License :: OSI Approved :: Python Software Foundation License',
                       'License :: OSI Approved :: MIT License'])
