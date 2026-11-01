# frozen_string_literal: true

require "json"

# Une aide locale.
module Helper
  def self.dump(value) = JSON.generate(value)
end
