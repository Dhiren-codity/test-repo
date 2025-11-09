require 'rails_helper' rescue nil
begin
  require 'spec_helper'
rescue LoadError
end
require 'rack/test'
require 'json'
require 'time'
require_relative '../app/app'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze additional cases' do
    it 'returns 400 when content is missing' do
      post '/analyze', { path: 'file.rb' }
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing content')
    end

    it 'falls back to params when JSON body is invalid' do
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'puts 1', path: 'test.rb'))
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'puts 1', language: 'ruby'))
        .and_return({ 'score' => 92.0, 'issues' => [] })

      post '/analyze?content=puts+1&path=test.rb', 'INVALID_JSON', { 'CONTENT_TYPE' => 'application/json' }
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json.dig('summary', 'language')).to eq('ruby')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when required params are missing' do
      post '/diff', { old_content: 'old' }
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing old_content or new_content')
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing content')
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing files array')
    end
  end
end