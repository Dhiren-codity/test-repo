require 'rails_helper'
begin
  require 'polyglot_api'
rescue LoadError
  require File.expand_path('../../polyglot_api', __FILE__)
end

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

  describe 'POST /analyze' do
    it 'returns 400 when content is missing' do
      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end
  end

  describe 'POST /diff' do
    it 'returns diff and new code review on success' do
      old_content = "puts 'old'"
      new_content = "puts 'new'"
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: old_content, new_content: new_content))
        .and_return({ 'changes' => 1, 'diff' => "+ puts 'new'\n- puts 'old'" })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: new_content))
        .and_return({ 'score' => 75.5, 'issues' => [] })

      post '/diff', { old_content: old_content, new_content: new_content }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']).to include('changes' => 1)
      expect(json_response['new_code_review']).to include('score' => 75.5)
    end

    it 'returns 400 when old_content or new_content is missing' do
      post '/diff', { old_content: 'only one' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing old_content or new_content')
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing files array')
    end
  end
end