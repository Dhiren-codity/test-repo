require 'rack'
require 'json'

class PolyglotAPI
  def self.call(env)
    new.call(env)
  end

  def call(env)
    req = Rack::Request.new(env)

    case [req.request_method, req.path_info]
    when ['GET', '/health']
      respond_json(200, { status: 'healthy', service: 'ruby-api' })
    when ['POST', '/analyze']
      data = parse_json_body(req)
      content = data['content'] || data[:content]
      return respond_json(400, { error: 'Missing content' }) unless content

      respond_json(200, { ok: true })
    when ['POST', '/diff']
      data = parse_json_body(req)
      old_content = data['old_content'] || data[:old_content]
      new_content = data['new_content'] || data[:new_content]
      return respond_json(400, { error: 'Missing old_content or new_content' }) unless old_content && new_content

      respond_json(200, { ok: true })
    when ['POST', '/metrics']
      data = parse_json_body(req)
      content = data['content'] || data[:content]
      return respond_json(400, { error: 'Missing content' }) unless content

      respond_json(200, { ok: true })
    when ['POST', '/dashboard']
      data = parse_json_body(req)
      files = data['files'] || data[:files]
      return respond_json(400, { error: 'Missing files array' }) if files.nil? || (files.respond_to?(:empty?) && files.empty?)

      respond_json(200, { ok: true })
    else
      respond_json(404, { error: 'Not Found' })
    end
  end

  private

  def parse_json_body(req)
    body = req.body.read
    req.body.rewind
    return {} if body.nil? || body.strip.empty?

    JSON.parse(body)
  rescue JSON::ParserError
    {}
  end

  def respond_json(status, obj)
    [status, { 'Content-Type' => 'application/json' }, [JSON.generate(obj)]]
    end
end