# frozen_string_literal: true

require "sinatra/base"

# Une application Sinatra minimale.
class Demo < Sinatra::Base
  get("/") { "Bonjour" }
end
