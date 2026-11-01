# frozen_string_literal: true

Gem::Specification.new do |spec|
  spec.name = "demo"
  spec.version = "0.1.0"
  spec.summary = "Mini-projet Bundler de forceupdate"
  spec.authors = ["forceupdate"]
  spec.files = ["lib/demo.rb"]

  spec.add_dependency "mustermann", "~> 2.0"
  spec.add_runtime_dependency "tilt", ">= 2.0.10"
  spec.add_development_dependency "diff-lcs", "~> 1.4"
end
